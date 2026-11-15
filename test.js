// Run the flow's function bodies the way Node-RED does, against the saved printer pages.
const fs = require('fs');
const F = JSON.parse(fs.readFileSync('funcs.json'));
const ctx = {};
const flow = {get: k => ctx[k], set: (k, v) => { ctx[k] = v; }};
const node = {status() {}, error(e) { throw new Error('node.error: ' + e); }, warn: w => console.log('   node.warn:', w)};
const run = (code, msg) => new Function('msg', 'flow', 'node', code)(msg, flow, node);

// link
let r = run(F.F_LINK, {payload: 'off'}); console.log('link off ->', JSON.stringify(r[0].payload), 'poll:', r[1]);
r = run(F.F_LINK, {payload: 'off'}); console.log('link off again ->', r);
r = run(F.F_LINK, {payload: 'unavailable'}); console.log('link unavailable ->', r);
r = run(F.F_LINK, {payload: 'on'}); console.log('link on ->', r[0].payload.status, 'poll:', !!r[1]);

// poll chain
let g = run(F.F_GATE, {payload: 'first poll'}); let m = g[0]; console.log('gate (first poll) full:', m.poll.full, m.url.split('/').pop());
m.statusCode = 200; m.payload = fs.readFileSync('samples/cons.xml', 'utf8');
m = run(F.F_CONS, m); console.log('ink', JSON.stringify(m.poll.ink));
m.statusCode = 200; m.payload = fs.readFileSync('samples/status.xml', 'utf8');
m = run(F.F_STATUS, m); console.log('categories', m.poll.categories, 'alerts', JSON.stringify(m.poll.alerts));
m.payload = [{oid: '1.3.6.1.2.1.25.3.5.1.1.1', value: 3}, {oid: '1.3.6.1.2.1.1.3.0', value: 89602}, {oid: '1.3.6.1.2.1.43.10.2.1.4.1.1', value: 15616}];
r = run(F.F_BUILD, m); r[0].forEach(o => console.log(o.topic, JSON.stringify(o.payload).slice(0, 400)));
r = run(F.F_BUILD, m); console.log('same data again publishes', r[0].length, 'message(s)');

// quick polls: status page only, ink from the last full poll; mode from status categories
const statusXml = fs.readFileSync('samples/status.xml', 'utf8');
const snmp = [{oid: '1.3.6.1.2.1.25.3.5.1.1.1', value: 3}, {oid: '1.3.6.1.2.1.1.3.0', value: 89602}, {oid: '1.3.6.1.2.1.43.10.2.1.4.1.1', value: 15616}];
for (const [cat, snmpState] of [['scanProcessing', 3], ['copying', 4], ['printing', 4], ['ready', 3], ['inPowerSave', 3], ['cancelJob', 4], ['somethingNew', 4]]) {
    let q = run(F.F_GATE, {payload: 1});
    q = q[0] || q[1];
    q.statusCode = 200;
    q.payload = statusXml.replace(/<pscat:StatusCategory>inPowerSave</, '<pscat:StatusCategory>' + cat + '<');
    q = run(F.F_STATUS, q);
    q.payload = snmp.map(v => v.oid === '1.3.6.1.2.1.25.3.5.1.1.1' ? {oid: v.oid, value: snmpState} : v);
    const o = run(F.F_BUILD, q)[0];
    const pw = o.find(x => x.topic.endsWith('/power'));
    console.log('  ', cat.padEnd(14), 'full', String(q.poll.full).padEnd(5), '->', flow.get('status').padEnd(11), pw ? 'power msg' : '', o.some(x => x.topic.endsWith('/supplies')) ? 'supplies msg' : '');
}

// failure, then off stops polling
r = run(F.F_FAIL, {error: {message: 'ETIMEDOUT'}}); console.log('fail ->', JSON.stringify(r.payload));
run(F.F_LINK, {payload: 'off'}); console.log('gate when off ->', run(F.F_GATE, {payload: 1}));

// discovery
r = run(F.F_DISCOVERY, {}); console.log('discovery', r[0].length, r[0].map(o => o.topic.split('/').slice(1, 4).join('/')).join(' '));
console.log(JSON.stringify(r[0][7].payload));
