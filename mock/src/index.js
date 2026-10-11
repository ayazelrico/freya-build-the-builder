// Mock of Freya Bank's statement services for the final case, following the 2026-10-01 service contract and
// test-environment/test-customers.md: POST <base>/voice/v1/<service>, request {data: {...}, call: {...}},
// answers served exactly from test-customers.json (status code and body, with the optional delay).
import DATA from "./test-customers.json";

const SERVICES = ["cards.list", "cards.balance", "statement.week.get", "statement.week.decide",
                  "statement.week.change", "contact.email.get", "statement.pdf.send"];
// Contract section 4: the 404 of each service; services without one answer 400 INVALID_ARGUMENTS_ERROR.
const NOT_FOUND = {
  "cards.list": ["FB_IVR_CHANNEL_102", "Müşteriye ait geçerli kart bilgisi bulunamadı."],
  "cards.balance": ["FB_IVR_CHANNEL_120", "Card not found"],
  "statement.week.get": ["FB_IVR_CHANNEL_121", "Card not found"],
  "statement.pdf.send": ["FB_IVR_CHANNEL_107", "Pdf dokümanı bulunamadı"],
};
const REQUIRED = {
  "cards.list": ["customerNo"], "cards.balance": ["cardNumber"], "statement.week.get": ["cardNumber"],
  "statement.week.decide": ["cardNumber", "newStatementWeek"], "statement.week.change": ["cardNumber", "newStatementWeek"],
  "contact.email.get": ["customerNo"], "statement.pdf.send": ["customerNo", "cardNumber"],
};
const FIELD_LABEL = { customerNo: "customer number", cardNumber: "card number", newStatementWeek: "new statement week" };

function guid() { return crypto.randomUUID().replace(/-/g, ""); }
function errorBody(httpStatus, code, message, type) {
  const g = guid();
  return [{ result: { guid: g, returnCode: code, messageText: message, code, message, type,
            details: { guid: g, rootCause: httpStatus >= 500 ? "TechnicalError" : "BusinessError", errorOrigin: "freya-final-mock" } } }, httpStatus];
}
function notFound(svc) {
  if (NOT_FOUND[svc]) return errorBody(404, NOT_FOUND[svc][0], NOT_FOUND[svc][1], "WARNING");
  return errorBody(400, "INVALID_ARGUMENTS_ERROR", "invalid arguments", "ERROR");
}

const sleep = (s) => new Promise((r) => setTimeout(r, Number(s) * 1000));
const CARD_OWNER = {};
for (const c of DATA.customers) for (const v of Object.values(c.services))
  if (v && typeof v === "object" && v.http === undefined) for (const card of Object.keys(v)) CARD_OWNER[card] = c;

function serviceFor(path) {
  const last = decodeURIComponent(path.split("/").filter(Boolean).pop() || "");
  if (SERVICES.includes(last)) return last;
  const n = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  const p = n(path.replace(/^\/+(voice\/)?(v\d+\/)?/i, ""));
  return SERVICES.find((s) => n(s) === p) || SERVICES.find((s) => p.endsWith(n(s)));
}

async function answer(svc, d) {
  for (const f of REQUIRED[svc] || []) {
    if (d[f] === undefined || d[f] === null || String(d[f]).trim() === "")
      return errorBody(400, "INVALID_ARGUMENTS_ERROR", `${FIELD_LABEL[f] || f} cannot be empty`, "ERROR");
  }
  let entry;
  if (["cards.list", "contact.email.get", "statement.pdf.send"].includes(svc)) {
    const cust = DATA.customers.find((c) => c.customerNo === String(d.customerNo).trim());
    entry = cust && cust.services[svc];
  } else {
    const card = String(d.cardNumber).trim();
    const cust = CARD_OWNER[card];
    entry = cust && cust.services[svc] && cust.services[svc][card];
    if (entry && entry.http === undefined) entry = entry[String(d.newStatementWeek).trim()];
  }
  if (!entry || entry.http === undefined) return notFound(svc);
  const delay = entry.delaySeconds ?? entry.gecikmeSaniye;
  if (delay) await sleep(delay);
  return [entry.response ?? entry.yanit ?? {}, entry.http];
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/health") return Response.json({ ok: true, customers: DATA.customers.length });
    const svc = serviceFor(url.pathname);
    if (!svc) return Response.json(...errorBody(404, "NOT_FOUND", `unknown service ${url.pathname}`, "ERROR").map((x, i) => (i ? { status: x } : x)));
    let body = {};
    try { body = await request.json(); } catch (e) { body = {}; }
    const d = (body && typeof body.data === "object" && body.data) ? body.data : (body || {});   // tolerate a missing envelope
    const [out, status] = await answer(svc, d);
    return Response.json(out, { status });
  },
};
