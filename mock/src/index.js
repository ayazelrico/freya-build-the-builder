// Mock of Freya Bank's statement services (final case). Data-driven: every answer comes from the bank's
// test-customers.json (status code, body and optional delay), looked up by customer number, card and week.
import DATA from "./test-customers.json";

// Exact paths from the integration document go here; until then the path is matched to a service name loosely.
const PATHS = {};

const SERVICES = ["cards.list", "cards.balance", "statement.week.get", "statement.week.decide",
                  "statement.week.change", "contact.email.get", "statement.pdf.send"];
const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");

function serviceFor(path) {
  if (PATHS[path]) return PATHS[path];
  const p = norm(path.replace(/^\/+(api\/)?(v\d+\/)?/i, ""));
  return SERVICES.find((s) => norm(s) === p) || SERVICES.find((s) => p.endsWith(norm(s))) ||
         SERVICES.find((s) => p.includes(norm(s)));
}

function pick(obj, names) {
  for (const n of names) {
    for (const k of Object.keys(obj || {})) if (k.toLowerCase() === n.toLowerCase() && obj[k] !== undefined && obj[k] !== "") return obj[k];
  }
  return undefined;
}

function cardEntry(table, card) {
  if (!table) return undefined;
  if (table[card]) return table[card];
  const digits = String(card || "").replace(/\D/g, "");
  const keys = Object.keys(table);
  const byLast = keys.filter((k) => digits && k.replace(/\D/g, "").slice(-4) === digits.slice(-4));
  const exact = keys.find((k) => k.replace(/\*/g, "") && digits.endsWith(k.replace(/\D/g, "").slice(-4)) && digits.startsWith(k.replace(/\D/g, "").slice(0, 6)));
  if (exact) return table[exact];
  if (byLast.length === 1) return table[byLast[0]];
  if (keys.length === 1 && !card) return table[keys[0]];
  return undefined;
}

const sleep = (s) => new Promise((r) => setTimeout(r, Math.min(Number(s) || 0, 25) * 1000));

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/health") return Response.json({ ok: true, customers: DATA.customers.length });
    let body = {};
    if (request.method !== "GET") { try { body = await request.json(); } catch (e) { body = {}; } }
    const q = Object.fromEntries(url.searchParams);
    const args = { ...q, ...(body && typeof body === "object" ? body : {}) };
    const svc = serviceFor(url.pathname);
    if (!svc) return Response.json({ error: "unknown service", path: url.pathname }, { status: 404 });
    const cno = String(pick(args, ["customerNo", "customerNumber", "musteriNo", "customerId"]) || "").replace(/\D/g, "");
    const cust = DATA.customers.find((c) => c.customerNo === cno);
    if (!cust) return Response.json({ data: null, result: { returnCode: "0", code: "0", message: "Customer not found", messageText: "Customer not found" } }, { status: 404 });
    let entry = cust.services[svc];
    if (entry && entry.http === undefined) {          // keyed by card
      entry = cardEntry(entry, pick(args, ["cardNumber", "kartNo", "cardNo", "card"]));
      if (entry && entry.http === undefined) {        // keyed by requested week
        const wk = String(pick(args, ["newStatementWeek", "statementWeek", "week"]) ?? "");
        entry = entry[wk] || (Object.keys(entry).length === 1 ? Object.values(entry)[0] : undefined);
      }
    }
    if (!entry) return Response.json({ data: null, result: { returnCode: "0", code: "0", message: "No test data for this request", messageText: "No test data for this request" } }, { status: 404 });
    if (entry.gecikmeSaniye) await sleep(entry.gecikmeSaniye);
    return Response.json(entry.response ?? entry.yanit ?? {}, { status: entry.http || 200 });
  },
};
