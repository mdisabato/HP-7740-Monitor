// Run the flow's function bodies the way Node-RED does, against the saved printer pages.
const fs = require('fs');
const F = JSON.parse(fs.readFileSync('funcs.json'));
const ctx = {};
const flow = {get: k => ctx[k], set: (k, v) => { ctx[k] = v; }};
const node = {status() {}, error(e) { throw new Error('node.error: ' + e); }, warn: console.warn};
const run = (code, msg) => new Function('msg', 'flow', 'node', code)(msg, flow, node);

// link
let r = run(F.F_LINK, {payload: 'off'}); console.log('link off ->', JSON.stringify(r[0].payload), 'poll:', r[1]);
r = run(F.F_LINK, {payload: 'off'}); console.log('link off again ->', r);
r = run(F.F_LINK, {payload: 'unavailable'}); console.log('link unavailable ->', r);
r = run(F.F_LINK, {payload: 'on'}); console.log('link on ->', r[0].payload.status, 'poll:', !!r[1]);

// poll chain
let m = run(F.F_GATE, {payload: 1}); console.log('gate url', m.url);
m.statusCode = 200; m.payload = fs.readFileSync('samples/cons.xml', 'utf8');
m = run(F.F_CONS, m); console.log('ink', JSON.stringify(m.poll.ink));
m.statusCode = 200; m.payload = fs.readFileSync('samples/status.xml', 'utf8');
m = run(F.F_STATUS, m); console.log('categories', m.poll.categories, 'alerts', JSON.stringify(m.poll.alerts));
m.payload = [{oid: '1.3.6.1.2.1.25.3.5.1.1.1', value: 3}, {oid: '1.3.6.1.2.1.1.3.0', value: 89602}, {oid: '1.3.6.1.2.1.43.10.2.1.4.1.1', value: 15616}];
r = run(F.F_BUILD, m); r[0].forEach(o => console.log(o.topic, JSON.stringify(o.payload).slice(0, 400)));
r = run(F.F_BUILD, m); console.log('second build publishes', r[0].length, 'message(s)');

// failure, then off stops polling
r = run(F.F_FAIL, {error: {message: 'ETIMEDOUT'}}); console.log('fail ->', JSON.stringify(r.payload));
run(F.F_LINK, {payload: 'off'}); console.log('gate when off ->', run(F.F_GATE, {payload: 1}));

// discovery
r = run(F.F_DISCOVERY, {}); console.log('discovery', r[0].length, r[0].map(o => o.topic.split('/').slice(1, 4).join('/')).join(' '));
console.log(JSON.stringify(r[0][7].payload));
