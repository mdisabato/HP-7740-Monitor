"""Build the Node-RED "HP 7740 Monitor" tab as JSON for POST /flow (or Import in the editor).

Settings come from settings.json (copy settings.example.json). Writes flow.json and funcs.json.
"""
import json

CFG = json.load(open('settings.json'))
TAB = 'hp7740_tab'
HOST = CFG['printer_host']
LINK = CFG['link_entity']
SERVER = CFG['ha_server_id']        # Home Assistant server config node
BROKER = CFG['mqtt_broker_id']      # MQTT broker config node
BASE = CFG.get('topic_base', 'hp7740')
IGNORE_TRAYS = CFG.get('ignore_trays', [])
COMMUNITY = CFG.get('snmp_community', 'public')
POLL = str(CFG.get('poll_seconds', 15))            # status page + SNMP
INK_EVERY = int(CFG.get('ink_every_polls', 4))      # consumables page every Nth poll
BOOT = str(CFG.get('boot_delay_seconds', 45))

F_LINK = r"""// Switch port link = printer power. The printer's NIC powers down when it is off.
const s = msg.payload;
if (s !== 'on' && s !== 'off') return null;          // unavailable/unknown: keep the last state
const on = s === 'on';
const was = flow.get('link');
flow.set('link', s);
if (was === s) return null;                           // no change (e.g. HA reconnect)
const status = on ? 'starting' : 'off';
flow.set('status', status);
const power = {power: s, status, changed: new Date().toISOString()};
node.status({fill: on ? 'green' : 'grey', shape: 'dot', text: status});
return [{topic: 'BASE/power', payload: power}, on ? {payload: 'first poll'} : null];
""".replace('BASE', BASE)

F_GATE = r"""// Poll only while the link is up. Status page + SNMP every poll; ink every INK_EVERY polls.
if (flow.get('link') !== 'on') return null;
const n = (flow.get('polls') || 0);
flow.set('polls', n + 1);
const full = msg.payload === 'first poll' || n % INK_EVERY === 0 || !flow.get('ink');
msg.method = 'GET';
msg.requestTimeout = 8000;
msg.poll = {started: Date.now(), full};
if (full) { msg.url = 'http://HOST/DevMgmt/ConsumableConfigDyn.xml'; return [msg, null]; }
msg.url = 'http://HOST/DevMgmt/ProductStatusDyn.xml';
return [null, msg];
""".replace('HOST', HOST).replace('INK_EVERY', str(INK_EVERY))

F_CONS = r"""// Ink levels from the printer's consumables page.
if (msg.statusCode !== 200) { node.error('consumables page: HTTP ' + msg.statusCode, msg); return null; }
const x = String(msg.payload);
const COLORS = {C: 'cyan', M: 'magenta', Y: 'yellow', K: 'black'};
const ink = {};
for (const m of x.matchAll(/<ccdyn:ConsumableInfo>([\s\S]*?)<\/ccdyn:ConsumableInfo>/g)) {
    const b = m[1];
    const g = t => (b.match(new RegExp('<dd:' + t + '>([^<]*)</dd:' + t + '>')) || [])[1];
    if (g('ConsumableTypeEnum') !== 'ink') continue;
    const c = COLORS[g('ConsumableLabelCode')];
    if (!c) continue;
    const pct = g('ConsumablePercentageLevelRemaining');
    const life = (b.match(/<dd:ConsumableLifeState>([\s\S]*?)<\/dd:ConsumableLifeState>/) || [])[1] || '';
    const lg = t => (life.match(new RegExp('<dd:' + t + '>([^<]*)</dd:' + t + '>')) || [])[1];
    // MeasuredQuantityState says ok/low/... even for third-party cartridges; ConsumableState then says "nonHP"
    let level = lg('MeasuredQuantityState') || lg('ConsumableState') || 'unknown';
    if (level === 'nonHP') level = 'ok';
    ink[c] = {pct: pct === undefined ? null : Number(pct), level, brand: lg('Brand') || null};
}
msg.poll.ink = ink;
flow.set('ink', ink);
msg.url = 'http://HOST/DevMgmt/ProductStatusDyn.xml';
return msg;
""".replace('HOST', HOST)

F_STATUS = r"""// Status categories and the alert table, minus the nags we don't care about.
if (msg.statusCode !== 200) { node.error('status page: HTTP ' + msg.statusCode, msg); return null; }
const x = String(msg.payload);
const IGNORE_TRAYS = JSON_TRAYS;
const IGNORE = /^(nonHP|genuineHP|usedSupply|refilled|counterfeit|firmware|webServices|ePrint|cartridgeLow|cartridgeVeryLow|inkLow|inkVeryLow)/i;
const cats = [...x.matchAll(/<pscat:StatusCategory>([^<]*)</g)].map(m => m[1]);
const alerts = [];
for (const m of x.matchAll(/<psdyn:Alert>([\s\S]*?)<\/psdyn:Alert>/g)) {
    const b = m[1];
    const id = (b.match(/<ad:ProductStatusAlertID>([^<]*)</) || [])[1];
    if (!id || IGNORE.test(id)) continue;
    const bin = (b.match(/<ad:AlertDetailsInputBin>([^<]*)</) || [])[1];
    if (bin && IGNORE_TRAYS.includes(bin)) continue;
    const sev = (b.match(/<ad:Severity>([^<]*)</) || [])[1] || '';
    const color = (b.match(/<ad:AlertDetailsMarkerColor>([^<]*)</) || [])[1];
    alerts.push({id, severity: sev, detail: bin || color || null});
}
msg.poll.categories = cats;
msg.poll.alerts = alerts;
msg.payload = '';
return msg;
""".replace('JSON_TRAYS', json.dumps(IGNORE_TRAYS))

F_BUILD = r"""// Combine SNMP with the page data and publish.
const vb = {};
for (const v of (Array.isArray(msg.payload) ? msg.payload : [])) vb[v.oid] = v.value;
const prt = Number(vb['1.3.6.1.2.1.25.3.5.1.1.1']);          // hrPrinterStatus
const up = Number(vb['1.3.6.1.2.1.1.3.0']);                  // sysUpTime, 1/100 s
const pages = vb['1.3.6.1.2.1.43.10.2.1.4.1.1'];             // prtMarkerLifeCount
const p = msg.poll;
p.ink = p.ink || flow.get('ink') || {};
// Mode from the printer's status categories (what the front panel shows), most specific first.
const MODES = [['cancelJob', 'cancelling'], ['scanProcessing', 'scanning'], ['scanning', 'scanning'],
               ['copying', 'copying'], ['faxSending', 'faxing'], ['faxReceiving', 'faxing'],
               ['printing', 'printing'], ['processing', 'printing'], ['initializing', 'warming up'],
               ['busy', 'busy'], ['inPowerSave', 'sleep'], ['ready', 'ready']];
const hit = MODES.find(([c]) => p.categories.includes(c));
let status = hit ? hit[1] : ({3: 'ready', 4: 'printing', 5: 'warming up'}[prt] || 'unknown');
if (!hit) node.warn('no known mode in categories: ' + p.categories.join(', '));
const now = Date.now();
const supplies = {
    ink_cyan: p.ink.cyan ? p.ink.cyan.pct : null,
    ink_magenta: p.ink.magenta ? p.ink.magenta.pct : null,
    ink_yellow: p.ink.yellow ? p.ink.yellow.pct : null,
    ink_black: p.ink.black ? p.ink.black.pct : null,
    ink_low: Object.entries(p.ink).filter(([c, i]) => i.level !== 'ok').map(([c, i]) => c + ' ' + i.level).join(', ') || 'none',
    ink: p.ink,
    pages: pages === undefined ? null : Number(pages),
    alert: p.alerts.length ? p.alerts.map(a => a.id + (a.detail ? ' (' + a.detail + ')' : '')).join(', ') : 'none',
    alerts: p.alerts,
    categories: p.categories,
    powered_on: isNaN(up) ? null : new Date(Math.round((now - up * 10) / 60000) * 60000).toISOString(),
    updated: new Date(now).toISOString(),
};
const changedStatus = flow.get('status') !== status;
flow.set('status', status);
node.status({fill: 'green', shape: 'dot', text: status + ', black ' + supplies.ink_black + '%'});
const key = JSON.stringify(Object.assign({}, supplies, {updated: null}));
const out = [];
if (key !== flow.get('supplies_key') || p.full) { flow.set('supplies_key', key); out.push({topic: 'BASE/supplies', payload: supplies}); }
if (changedStatus) out.push({topic: 'BASE/power', payload: {power: 'on', status, changed: new Date(now).toISOString()}});
return [out];
""".replace('BASE', BASE)

F_FAIL = r"""// A poll failed while the link is up: the printer is powered but not answering.
if (flow.get('link') !== 'on') return null;
if (flow.get('status') === 'not responding') return null;
flow.set('status', 'not responding');
node.status({fill: 'yellow', shape: 'ring', text: 'not responding'});
return {topic: 'BASE/power', payload: {power: 'on', status: 'not responding', changed: new Date().toISOString(),
        error: String((msg.error && msg.error.message) || 'poll failed')}};
""".replace('BASE', BASE)

F_DISCOVERY = r"""// Home Assistant MQTT discovery, retained.
const dev = {identifiers: ['hp7740_monitor'], name: 'HP 7740 Monitor', manufacturer: 'HP',
             model: 'OfficeJet Pro 7740', configuration_url: 'http://HOST/'};
const P = 'BASE/power', S = 'BASE/supplies';
const ents = [
  ['binary_sensor', 'power', 'Power', P, '{{ value_json.power | upper }}', {device_class: 'power', payload_on: 'ON', payload_off: 'OFF'}],
  ['sensor', 'status', 'Status', P, '{{ value_json.status }}', {icon: 'mdi:printer'}],
  ['sensor', 'ink_cyan', 'Ink cyan', S, '{{ value_json.ink_cyan }}', {unit_of_measurement: '%', state_class: 'measurement', icon: 'mdi:water'}],
  ['sensor', 'ink_magenta', 'Ink magenta', S, '{{ value_json.ink_magenta }}', {unit_of_measurement: '%', state_class: 'measurement', icon: 'mdi:water'}],
  ['sensor', 'ink_yellow', 'Ink yellow', S, '{{ value_json.ink_yellow }}', {unit_of_measurement: '%', state_class: 'measurement', icon: 'mdi:water'}],
  ['sensor', 'ink_black', 'Ink black', S, '{{ value_json.ink_black }}', {unit_of_measurement: '%', state_class: 'measurement', icon: 'mdi:water'}],
  ['sensor', 'ink_low', 'Ink low', S, '{{ value_json.ink_low }}', {icon: 'mdi:water-alert'}],
  ['sensor', 'alert', 'Alert', S, '{{ value_json.alert }}', {icon: 'mdi:alert-outline'}],
  ['sensor', 'pages', 'Pages printed', S, '{{ value_json.pages }}', {state_class: 'total_increasing', icon: 'mdi:counter'}],
  ['sensor', 'powered_on', 'Powered on', S, '{{ value_json.powered_on }}', {device_class: 'timestamp'}],
];
return [ents.map(([comp, key, name, topic, tpl, extra]) => ({
    topic: `homeassistant/${comp}/hp7740/${key}/config`,
    payload: Object.assign({name, unique_id: `hp7740_${key}`, default_entity_id: `${comp}.hp7740_${key}`,
        state_topic: topic, value_template: tpl, device: dev}, extra,
        key === 'alert' || key === 'ink_low' ? {json_attributes_topic: S, json_attributes_template: key === 'alert' ? '{{ {"alerts": value_json.alerts, "categories": value_json.categories} | tojson }}' : '{{ {"ink": value_json.ink} | tojson }}'} : {}),
}))];
""".replace('HOST', HOST).replace('BASE', BASE)


def fn(id_, name, code, x, y, wires, outputs=1):
    return {'id': id_, 'type': 'function', 'z': TAB, 'name': name, 'func': code, 'outputs': outputs,
            'timeout': 0, 'noerr': 0, 'initialize': '', 'finalize': '', 'libs': [], 'x': x, 'y': y, 'wires': wires}


def http(id_, name, x, y, wires):
    return {'id': id_, 'type': 'http request', 'z': TAB, 'name': name, 'method': 'use', 'ret': 'txt',
            'paytoqs': 'ignore', 'url': '', 'tls': '', 'persist': False, 'proxy': '', 'insecureHTTPParser': False,
            'authType': '', 'senderr': True, 'headers': [], 'x': x, 'y': y, 'wires': wires}


nodes = [
    {'id': 'hp7740_cmt', 'type': 'comment', 'z': TAB, 'name': 'HP 7740 monitor: power from the switch port link; while on, status pages (HTTP) + SNMP every ' + POLL + ' s (ink every ' + str(INK_EVERY) + ' polls); published to MQTT ' + BASE + '/power and ' + BASE + '/supplies (retained) with HA discovery',
     'info': 'Replaces the HACS hpprinter integration. Ignores non-HP cartridge, firmware and web-services nags and empty ignored trays.', 'x': 520, 'y': 40, 'wires': []},
    # discovery
    {'id': 'hp7740_disc_inj', 'type': 'inject', 'z': TAB, 'name': 'publish discovery at start', 'props': [{'p': 'payload'}],
     'repeat': '', 'crontab': '', 'once': True, 'onceDelay': '5', 'topic': '', 'payload': '', 'payloadType': 'date',
     'x': 170, 'y': 100, 'wires': [['hp7740_disc']]},
    fn('hp7740_disc', 'Discovery configs', F_DISCOVERY, 420, 100, [['hp7740_mqtt']]),
    # link
    {'id': 'hp7740_link', 'type': 'server-state-changed', 'z': TAB, 'name': 'Printer link (switch port)', 'server': SERVER,
     'version': 6, 'outputs': 1, 'exposeAsEntityConfig': '', 'entities': {'entity': [LINK], 'substring': [], 'regex': []},
     'outputInitially': True, 'stateType': 'str', 'ifState': '', 'ifStateType': 'str', 'ifStateOperator': 'is',
     'outputOnlyOnStateChange': True, 'for': '0', 'forType': 'num', 'forUnits': 'minutes', 'ignorePrevStateNull': False,
     'ignorePrevStateUnknown': False, 'ignorePrevStateUnavailable': False, 'ignoreCurrentStateUnknown': True,
     'ignoreCurrentStateUnavailable': True,
     'outputProperties': [{'property': 'payload', 'propertyType': 'msg', 'value': '', 'valueType': 'entityState'}],
     'x': 190, 'y': 180, 'wires': [['hp7740_fl']]},
    fn('hp7740_fl', 'Link → power', F_LINK, 420, 180, [['hp7740_mqtt'], ['hp7740_wait']], outputs=2),
    {'id': 'hp7740_wait', 'type': 'delay', 'z': TAB, 'name': 'let it boot', 'pauseType': 'delay', 'timeout': BOOT,
     'timeoutUnits': 'seconds', 'rate': '1', 'nbRateUnits': '1', 'rateUnits': 'second', 'randomFirst': '1',
     'randomLast': '5', 'randomUnits': 'seconds', 'drop': False, 'allowrate': False, 'outputs': 1, 'x': 610, 'y': 200,
     'wires': [['hp7740_gate']]},
    # poll
    {'id': 'hp7740_tick', 'type': 'inject', 'z': TAB, 'name': 'every ' + POLL + ' s', 'props': [{'p': 'payload'}],
     'repeat': POLL, 'crontab': '', 'once': True, 'onceDelay': '20', 'topic': '', 'payload': '', 'payloadType': 'date',
     'x': 150, 'y': 260, 'wires': [['hp7740_gate']]},
    fn('hp7740_gate', 'Poll if powered', F_GATE, 400, 260, [['hp7740_h1'], ['hp7740_h2']], outputs=2),
    http('hp7740_h1', 'Consumables page', 600, 260, [['hp7740_fc']]),
    fn('hp7740_fc', 'Parse ink', F_CONS, 790, 260, [['hp7740_h2']]),
    http('hp7740_h2', 'Status page', 600, 320, [['hp7740_fs']]),
    fn('hp7740_fs', 'Parse alerts', F_STATUS, 790, 320, [['hp7740_snmp']]),
    {'id': 'hp7740_snmp', 'type': 'snmp', 'z': TAB, 'host': HOST, 'version': '2c', 'timeout': '5', 'community': COMMUNITY,
     'auth': 'noAuthNoPriv', 'authprot': 'MD5', 'privprot': 'DES', 'oids': '1.3.6.1.2.1.25.3.5.1.1.1,1.3.6.1.2.1.1.3.0,1.3.6.1.2.1.43.10.2.1.4.1.1',
     'name': 'SNMP: state, uptime, pages', 'x': 600, 'y': 380, 'wires': [['hp7740_fb']]},
    fn('hp7740_fb', 'Build and publish', F_BUILD, 810, 380, [['hp7740_mqtt']]),
    # failures
    {'id': 'hp7740_catch', 'type': 'catch', 'z': TAB, 'name': 'poll failed',
     'scope': ['hp7740_h1', 'hp7740_h2', 'hp7740_snmp', 'hp7740_fc', 'hp7740_fs', 'hp7740_fb'], 'uncaught': False,
     'x': 150, 'y': 440, 'wires': [['hp7740_ff']]},
    fn('hp7740_ff', 'Mark not responding', F_FAIL, 400, 440, [['hp7740_mqtt']]),
    # out
    {'id': 'hp7740_mqtt', 'type': 'mqtt out', 'z': TAB, 'name': 'MQTT (retained)', 'topic': '', 'qos': '1', 'retain': 'true',
     'respTopic': '', 'contentType': '', 'userProps': '', 'correl': '', 'expiry': '', 'broker': BROKER,
     'x': 1060, 'y': 200, 'wires': []},
]

flow = {'id': TAB, 'label': 'HP 7740 Monitor', 'disabled': False,
        'info': 'Printer monitor that replaces the HACS hpprinter integration. See the comment node.', 'nodes': nodes, 'configs': []}
json.dump(flow, open('flow.json', 'w'), indent=1)
json.dump({'F_LINK': F_LINK, 'F_GATE': F_GATE, 'F_CONS': F_CONS, 'F_STATUS': F_STATUS, 'F_BUILD': F_BUILD,
           'F_FAIL': F_FAIL, 'F_DISCOVERY': F_DISCOVERY}, open('funcs.json', 'w'))
print(len(nodes), 'nodes')
