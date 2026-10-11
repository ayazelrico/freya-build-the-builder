"""Python snippets that run inside the Freya workflow (code nodes and tool hooks).

Every snippet is plain Python that reads its configuration from a DATA object embedded by
`embed()`. The platform may template `{{...}}` inside code, so no snippet may contain a double
brace. `check_code()` enforces that before a workflow is written.
"""
import json

# Shared helpers. Prepended to every snippet that needs dates or products.
LIB = r'''
import datetime, json, re
DATA = __DATA__
CAL = DATA.get('calendar') or dict()
HOL = set(CAL.get('holidays') or [])
BWD = set(CAL.get('business_weekdays') or [1, 2, 3, 4, 5])
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']

def V(name, default=None):
    try:
        x = vars.get(name)
    except Exception:
        return default
    return default if x is None else x

def S(name, value):
    try:
        vars[name] = value
    except Exception:
        pass

def now_dt():
    s = str(V('now', '') or '').strip()
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(s[:19], fmt)
        except Exception:
            pass
    try:
        return datetime.datetime.fromisoformat(s.replace('Z', ''))
    except Exception:
        return datetime.datetime.utcnow()

def is_bd(d):
    return d.isoweekday() in BWD and d.isoformat() not in HOL

def next_bd(d):
    d = d + datetime.timedelta(days=1)
    while not is_bd(d):
        d = d + datetime.timedelta(days=1)
    return d

def bd_on_or_after(d):
    while not is_bd(d):
        d = d + datetime.timedelta(days=1)
    return d

def add_bd(d, n):
    for _ in range(int(n)):
        d = next_bd(d)
    return d

def last_bd_of_week(d):
    monday = d - datetime.timedelta(days=d.weekday())
    for k in range(6, -1, -1):
        x = monday + datetime.timedelta(days=k)
        if is_bd(x):
            return x
    return None

def end_of_month(d):
    n = d.replace(day=28) + datetime.timedelta(days=4)
    return n - datetime.timedelta(days=n.day)

def say_date(d):
    return WEEKDAYS[d.weekday()] + ' ' + str(d.day) + ' ' + MONTHS[d.month - 1].capitalize()

def iso_say(d):
    return d.isoformat() + ' (' + say_date(d) + ')'

def money(x):
    try:
        x = float(x)
    except Exception:
        return str(x)
    s = ('%.2f' % x)
    if s.endswith('.00'):
        s = s[:-3]
    cw = DATA.get('currency_word') or ''
    return (s + ' ' + cw).strip()

def num(x):
    try:
        return float(str(x).replace(',', '').strip())
    except Exception:
        return None

def parse_date(s, order):
    """Read a date the agent wrote in almost any form. Numeric dates use `order` (DMY or MDY)."""
    s = str(s or '').strip().lower()
    if not s:
        return None
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    m = re.match(r'^(\d{1,2})[./ -](\d{1,2})[./ -](\d{2,4})$', s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 1900 if y > 30 else 2000
        d, mo = (b, a) if order == 'MDY' else (a, b)
        try:
            return datetime.date(y, mo, d)
        except Exception:
            return None
    t = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', s).replace(',', ' ').replace(' of ', ' ')
    mo = None
    for i, name in enumerate(MONTHS):
        if name in t or (' ' + name[:3] + ' ') in (' ' + t + ' '):
            mo = i + 1
            break
    nums = [int(x) for x in re.findall(r'\d+', t)]
    if mo and nums:
        y = [x for x in nums if x > 31]
        dd = [x for x in nums if x <= 31]
        try:
            return datetime.date(y[0] if y else now_dt().year, mo, dd[0])
        except Exception:
            return None
    return None

def clean_line(text):
    # Fill {call_variable} placeholders; drop any sentence that still has one we cannot fill.
    text = str(text or '')
    def sub(m):
        x = V(m.group(1))
        return str(x) if x not in (None, '') and not isinstance(x, (list, dict)) else m.group(0)
    text = re.sub(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', sub, text)
    parts = re.split(r'(?<=[.!?])\s+', text)
    return ' '.join([p for p in parts if '{' not in p and '}' not in p]).strip()

def agent_text(conv):
    # The transcript arrives as a list of {'role', 'content'} (JSON or Python repr) or as 'AGENT: ...' lines.
    msgs = None
    for parse in (json.loads, __import__('ast').literal_eval):
        try:
            msgs = parse(conv)
            break
        except Exception:
            pass
    if isinstance(msgs, list):
        return ' '.join([str(m.get('content') or '') for m in msgs if isinstance(m, dict) and str(m.get('role')) in ('assistant', 'agent', 'bot')]).lower()
    return ' '.join([ln for ln in conv.split('\n') if not ln.upper().startswith(('USER', 'CUSTOMER', 'HUMAN'))]).lower()

def products():
    raw = V('products_json', '')
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []
'''

# Initial code node: today, callback window.
SETUP = LIB + r'''
try:
    n = now_dt()
    today = n.date()
    cb = DATA.get('callback') or dict()
    facts = ['Now: ' + today.isoformat() + ' ' + n.strftime('%H:%M') + ', ' + say_date(today) + '.']
    if cb.get('enabled'):
        days = [today]
        if cb.get('days') == 'today_or_next_business_day':
            days = [today, next_bd(today)]
        elif cb.get('days') == 'next_business_day':
            days = [next_bd(today)]
        start, end = cb.get('window_start') or '00:00', cb.get('window_end') or '23:59'
        lines = []
        for d in days:
            lo = start
            if d == today and cb.get('must_be_after_now', True):
                earliest = (n + datetime.timedelta(minutes=int(cb.get('min_minutes_after_now') or 0))).strftime('%H:%M')
                if earliest >= end:
                    continue
                if earliest >= start:
                    lo = 'after ' + earliest
            lines.append(say_date(d) + ' (' + d.isoformat() + '), ' + lo + ' to ' + end)
        S('callback_window', '; or '.join(lines) if lines else 'none')
        tomorrow = today + datetime.timedelta(days=1)
        S('callback_facts', 'Allowed callback times: ' + V('callback_window', '') + '. Tomorrow is ' + say_date(tomorrow) + ' (' + tomorrow.isoformat() + ').')
    S('today_iso', today.isoformat())
    S('today_facts', ' '.join(facts))
    qs0 = ((DATA.get('identity') or dict()).get('questions') or [dict()])
    S('id_field_now', str(qs0[0].get('field') or ''))
    S('promises_recorded', '0')
    S('promises_all', 'no')
    S('setup_state', 'done')
except Exception as e:
    S('today_facts', 'Now: ' + str(V('now', '')))
    S('callback_facts', '')
    S('setup_state', 'error ' + str(e)[:80])
'''

# After get_account: every product's facts, deadlines, attempt plan, the debt statement.
COMPUTE = LIB + r'''
def read_products():
    acc = DATA.get('account') or dict()
    pf = acc.get('products_field') or 'products'
    cands = [V('account_products'), V('get_account_response.data.' + pf)]
    for c in cands:
        if isinstance(c, list):
            return c
        if isinstance(c, str) and c.strip().startswith('['):
            try:
                return json.loads(c)
            except Exception:
                try:
                    import ast
                    return ast.literal_eval(c)
                except Exception:
                    pass
    # flattened keys: get_account_response.data.products.0.past_due
    for c in [V(k) for k in list(vars.keys()) if k.endswith('_response.data.' + pf)]:
        if isinstance(c, list):
            return c
    # flattened keys: <node or tool>_response.data.products.0.past_due
    out = dict()
    pat = re.compile(r'_response\.data\.' + re.escape(pf) + r'\.(\d+)\.(.+)$')
    try:
        keys = list(vars.keys())
    except Exception:
        keys = []
    for k in keys:
        m = pat.search(k)
        if m:
            out.setdefault(int(m.group(1)), dict())[m.group(2)] = vars.get(k)
    return [out[i] for i in sorted(out)]

def band_for(days):
    for b in DATA.get('bands') or []:
        lo, hi = b.get('min_days_late'), b.get('max_days_late')
        if (lo is None or days >= lo) and (hi is None or days <= hi):
            return b
    bs = DATA.get('bands') or [dict(name='default', attempts=1, deadline=dict(type='business_days_after_today', n=5))]
    return bs[-1]

def deadline_for(b, today):
    dl = b.get('deadline') or dict()
    t, n = dl.get('type'), dl.get('n') or 0
    if t == 'business_days_after_today':
        return add_bd(today, n)
    if t == 'business_days_after_today_counting_today':
        return add_bd(today, max(int(n) - 1, 0)) if is_bd(today) else add_bd(today, n)
    if t == 'calendar_days_after_today':
        d = today + datetime.timedelta(days=int(n))
        while not is_bd(d):
            d = d - datetime.timedelta(days=1)
        return d
    if t == 'end_of_month':
        d = end_of_month(today)
        while not is_bd(d):
            d = d - datetime.timedelta(days=1)
        return d
    if t == 'end_of_next_month':
        d = end_of_month(end_of_month(today) + datetime.timedelta(days=1))
        while not is_bd(d):
            d = d - datetime.timedelta(days=1)
        return d
    if t == 'fixed_date':
        try:
            return datetime.date.fromisoformat(str(dl.get('date')))
        except Exception:
            pass
    return add_bd(today, n or 5)

def attempt_date(rule, today, deadline):
    if rule == 'last_business_day_this_week_or_next_if_today':
        d = last_bd_of_week(today)
        if d is None or d <= today:
            d = last_bd_of_week(today + datetime.timedelta(days=7))
    elif rule == 'last_business_day_this_week':
        d = last_bd_of_week(today) or today
    elif rule == 'next_business_day':
        d = next_bd(today)
    elif rule == 'today':
        d = bd_on_or_after(today)
    elif rule == 'deadline':
        d = deadline
    elif rule and rule.startswith('business_days_after_today:'):
        d = add_bd(today, int(rule.split(':')[1]))
    else:
        d = deadline
    if d > deadline:
        d = deadline
    return d

try:
    n = now_dt()
    today = n.date()
    raw = read_products()
    acc = DATA.get('account') or dict()
    types = DATA.get('product_types') or dict()
    plist = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            continue
        ptype = str(p.get(acc.get('type_field') or 'type') or '')
        tinfo = types.get(ptype) or dict()
        try:
            spoken = (tinfo.get('spoken') or ptype.replace('_', ' ')).format(**p)
        except Exception:
            spoken = ptype.replace('_', ' ')
        full = num(p.get(acc.get('past_due_field') or 'past_due'))
        days = int(num(p.get(acc.get('days_late_field') or 'days_late')) or 0)
        floor = num(p.get(tinfo.get('floor_field') or '')) if tinfo.get('floor_field') else None
        fl = DATA.get('floor') or dict()
        pct = tinfo.get('floor_percent') if tinfo.get('floor_percent') is not None else fl.get('percent_of_past_due')
        if floor is None and pct is not None and full is not None:
            floor = round(full * float(pct) / 100.0, 2)          # a floor defined as a share of the past-due amount
        if floor is None and (tinfo.get('floor_amount') is not None or fl.get('fixed_amount') is not None):
            floor = num(tinfo.get('floor_amount') if tinfo.get('floor_amount') is not None else fl.get('fixed_amount'))
        if floor is not None and fl.get('min_amount') is not None and full is not None:
            floor = max(floor, min(num(fl.get('min_amount')) or 0, full))
        if floor is None or (full is not None and floor > full):
            floor = full
        b = band_for(days)
        dl = deadline_for(b, today)
        att = int(b.get('attempts') or 1)
        plan = []
        bplan = b.get('attempts_plan') or b.get('attempts_override')   # a band may have its own offer plan
        for a in (bplan if isinstance(bplan, list) and bplan else (DATA.get('attempts') or [])[:att]):
            plan.append(dict(number=a.get('number'), amount_rule=a.get('amount'), date=attempt_date(a.get('date'), today, dl).isoformat()))
        plist.append(dict(index=i + 1, product_id=str(p.get(acc.get('id_field') or 'product_id') or ('p' + str(i + 1))), type=ptype,
                          spoken=spoken, full=full, floor=floor, floor_name=tinfo.get('floor_name') or 'minimum amount',
                          days_late=days, band=b.get('name') or '', deadline=dl.isoformat(), attempts=att, plan=plan))
    S('products_json', json.dumps(plist))
    S('product_count', str(len(plist)))
    L = DATA.get('lines') or dict()
    multi = len(plist) > 1
    parts = []
    for p in plist:
        parts.append('Your ' + p['spoken'] + ' has ' + money(p['full']) + ' past due, ' + str(p['days_late']) + ' days late.')
    intro = clean_line(L.get('debt_intro_multi' if multi else 'debt_intro') or L.get('debt_intro') or '')
    ask = clean_line(L.get('first_ask_multi' if multi else 'first_ask') or L.get('first_ask') or '')
    if not ask:
        ask = 'Can you pay all of them today?' if multi else 'Can you pay this today?'
    S('debt_statement', ' '.join([x for x in [intro] + parts + [ask] if x]))
    # Facts block for the negotiation prompt.
    F = ['TODAY: ' + iso_say(today) + ', time ' + n.strftime('%H:%M') + '.']
    for p in plist:
        F.append('')
        F.append('PRODUCT ' + str(p['index']) + ' of ' + str(len(plist)) + ': ' + p['spoken'] + ' (product_id ' + p['product_id'] + ')')
        F.append('- Full past-due amount: ' + money(p['full']) + ' (send as ' + str(p['full']) + ')')
        F.append('- Floor (' + p['floor_name'] + '): ' + money(p['floor']) + ' (send as ' + str(p['floor']) + '). Lowest amount you may record.')
        F.append('- Days late: ' + str(p['days_late']) + ', band ' + p['band'] + ', persuasion attempts allowed: ' + str(p['attempts']) + '.')
        dl = datetime.date.fromisoformat(p['deadline'])
        F.append('- DEADLINE (latest date you may record): ' + iso_say(dl) + '.')
        def offer(rule, ad, too_much):
            use_floor = rule == 'floor' or (rule == 'full_or_floor_if_full_refused' and too_much)
            tpl = (L.get('floor_offer') if use_floor else L.get('full_offer')) or ''
            amt = p['floor'] if use_floor else p['full']
            vals = dict(amount=money(amt), date=say_date(ad), floor_name=p['floor_name'], product=p['spoken'])
            try:
                txt = tpl.format(**vals) if tpl else ''
            except Exception:
                txt = ''
            if not txt:
                txt = 'Can you pay ' + ('the ' + p['floor_name'] + ' of ' if use_floor else 'the full ') + money(amt) + ' on ' + say_date(ad) + '?'
            return txt + '  [amount ' + str(amt) + ', date ' + ad.isoformat() + ']'
        seqs = [('if the customer refuses or does not answer', False)]
        if any(a['amount_rule'] == 'full_or_floor_if_full_refused' for a in p['plan']):
            seqs.append(('if the customer said the full amount is too much', True))
        for label, too_much in seqs:
            F.append('- OFFER SEQUENCE ' + label + ' (each offer at most once, in this order; say it exactly as written. ' + ('The question about paying today was already asked in your first message for all products: never ask about today again; when you turn to this product, your first proposal is offer 1' if len(plist) > 1 else 'The question about paying today is asked only once') + '):')
            for a in p['plan']:
                F.append('    offer ' + str(a['number']) + ': "' + offer(a['amount_rule'] or 'full', datetime.date.fromisoformat(a['date']), too_much) + '"')
        p['offers'] = []
        for a in p['plan']:
            ad = datetime.date.fromisoformat(a['date'])
            rule = a['amount_rule'] or 'full'
            amts = [p['floor']] if rule == 'floor' else ([p['full'], p['floor']] if rule == 'full_or_floor_if_full_refused' else [p['full']])
            p['offers'].append(dict(number=a['number'], date=a['date'], amounts=amts, text=offer(rule, ad, False).split('  [')[0]))
        F.append('    after the last offer is refused: no more offers for this product.')
    # Calendar: what to do for every date the customer may name.
    last = max([datetime.date.fromisoformat(p['deadline']) for p in plist] or [today]) + datetime.timedelta(days=21)
    F.append('')
    F.append('DATE LOOKUP. When the customer names a day, find it here and do exactly what its line says. (Proposing the deadline because they gave no day at all applies only when they name no day.)')
    d = today
    while d <= last:
        acts = []
        for p in plist:
            dl = datetime.date.fromisoformat(p['deadline'])
            who = ('for the ' + p['spoken'] + ': ') if len(plist) > 1 else ''
            if d > dl:
                acts.append(who + 'after the deadline, say the latest date you can record is ' + say_date(dl) + ' and offer that')
            elif not is_bd(d):
                pol = (DATA.get('calendar') or dict()).get('non_business_day') or 'next_business_day'
                kind = 'holiday' if d.isoformat() in HOL else 'weekend'
                if pol == 'refuse':
                    acts.append(who + 'not a business day (' + kind + '); it cannot be recorded')
                elif pol == 'previous_business_day':
                    pb = d - datetime.timedelta(days=1)
                    while not is_bd(pb):
                        pb = pb - datetime.timedelta(days=1)
                    acts.append(who + 'not a business day (' + kind + '); offer the previous business day, ' + say_date(max(pb, bd_on_or_after(today))))
                else:
                    nb = next_bd(d)
                    if nb > dl:
                        acts.append(who + 'not a business day; offer ' + say_date(dl) + ', the latest date you can record')
                    else:
                        acts.append(who + 'not a business day (' + kind + '); offer the next business day, ' + say_date(nb) + ' (' + nb.isoformat() + ')')
            else:
                acts.append(who + 'OK, can be recorded')
        F.append('- ' + say_date(d) + ' (' + d.isoformat() + ')' + (' = today' if d == today else '') + ': ' + '; '.join(acts))
        d = d + datetime.timedelta(days=1)
    S('negotiation_facts', '\n'.join(F))
    S('products_json', json.dumps(plist))
    S('account_state', 'loaded' if plist else 'empty')
except Exception as e:
    S('account_state', 'error')
    S('negotiation_facts', 'The account could not be read.')
    S('debt_statement', '')
    S('compute_error', str(e)[:200])
'''

# End of call: decide the final outcome and the farewell line from the end path taken
# (end_path_outcome / end_path_reason / end_path_role) and what really happened (transfer, promises, notes).
END = LIB + r'''
try:
    L = DATA.get('lines') or dict()
    O = DATA.get('outcomes') or []
    NT = DATA.get('notes') or dict()

    def row(rl, reason=None):
        rs = [r for r in O if (r.get('role') or 'other') == rl]
        if reason is not None:     # the mapped value can be the row's reason or, in some briefs, its outcome code
            rs = [r for r in rs if (r.get('reason') or '') == reason] or [r for r in rs if str(r.get('outcome')) == reason] or rs
        return rs[0] if rs else None

    outcome, reason = str(V('end_path_outcome', '') or ''), str(V('end_path_reason', '') or '')
    rl = str(V('end_path_role', '') or 'other')
    q2r = (DATA.get('transfer') or dict()).get('queue_to_reason') or dict()
    tq = str(V('transfer_done_queue', '') or '')
    rec = int(num(V('promises_recorded', '0')) or 0)
    pick = None
    if tq:
        pick = row('transferred', q2r.get(tq, tq))
    elif rec > 0:
        pick = row('promise')
    elif NT.get('enabled') and rl in ('refused', 'hardship', 'dispute', 'service_error', 'paid', 'promise', 'other'):
        try:
            notes = json.loads(V('notes_json', '[]') or '[]')
        except Exception:
            notes = []
        if notes:
            order = [p['product_id'] for p in products()]
            notes.sort(key=lambda x: order.index(x[0]) if x[0] in order else 99)
            paid_value = NT.get('paid_reason') or ''
            nonpaid = [x for x in notes if x[1] != paid_value]
            if not nonpaid:
                pick = row('paid')
            else:
                r0 = nonpaid[0][1]
                match = [r for r in O if (r.get('reason') or '') == r0]
                base = match[0] if match else (row('refused') or dict(outcome=outcome))
                pick = dict(base, reason=r0)
    if pick:
        outcome, reason, rl = pick.get('outcome') or outcome, pick.get('reason') or '', pick.get('role') or rl
    words = []
    if rl == 'promise':
        words += [L.get('promise_recorded') or '', L.get('sms_sentence') or '']
    elif rl == 'paid':
        words += [L.get('already_paid') or '']
    elif rl == 'deceased':
        words += [L.get('condolence') or '']
    elif rl == 'id_failed':
        words += [L.get('identity_failed') or '']
    elif rl == 'service_error':
        words += [L.get('service_error') or '']
    words += [L.get('goodbye') or 'Goodbye.']
    S('farewell_text', ' '.join([clean_line(w) for w in words if clean_line(w)]))
    S('close_outcome', outcome)
    S('close_reason', reason or '')
except Exception as e:
    S('farewell_text', 'Thank you. Goodbye.')
    S('close_outcome', str(V('end_path_outcome', '') or ''))
    S('close_reason', str(V('end_path_reason', '') or ''))
'''

# --- Tool hooks --------------------------------------------------------------------------
# Every post-hook adds result['data']['what_to_do_next'], a plain instruction the phone agent obeys.

VERIFY_PRE = LIB + r'''
try:
    I = DATA.get('identity') or dict()
    b = config.get('body')
    if isinstance(b, dict):
        f = str(b.get(I.get('field_param') or 'field') or '')
        ap = I.get('answer_param') or 'answer'
        q = [x for x in I.get('questions') or [] if x.get('field') == f]
        fmt = q[0].get('answer_format') if q else ''
        a = str(b.get(ap) or '').strip()
        if fmt == 'date':
            d = parse_date(a, I.get('numeric_date_order') or 'DMY')
            if d:
                b[ap] = d.isoformat()
        elif fmt == 'digits':
            ds = re.sub(r'\D', '', a)
            if ds:
                b[ap] = ds
        elif fmt == 'year':
            ds = re.findall(r'\d{4}', a)
            if ds:
                b[ap] = ds[0]
        S('id_last_field', f)
except Exception:
    pass
'''

VERIFY_POST = LIB + r'''
try:
    I = DATA.get('identity') or dict()
    R = I.get('response') or dict()
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if not isinstance(d, dict):
            d = dict()
            result['data'] = d
        qs = I.get('questions') or []
        f = str(V('id_last_field', '') or '')
        okset = [x for x in str(V('id_ok_fields', '') or '').split(',') if x]
        hint = d.get(R.get('hint') or 'hint')
        left = d.get(R.get('remaining') or 'wrong_answers_left')
        good = str(d.get(R.get('answer_ok') or 'verified')).lower() == 'true'
        allok = str(d.get(R.get('all_ok') or 'all_verified')).lower() == 'true'
        if good and f and f not in okset:
            okset.append(f)
            S('id_ok_fields', ','.join(okset))
        nxt = [x for x in qs if x.get('field') not in okset]
        hints = dict((h.get('value'), h.get('instruction')) for h in I.get('hints') or [])
        cur = [x for x in qs if x.get('field') == f]
        cur_ask = cur[0].get('ask') if cur else 'the same question'
        if allok:
            msg = 'Identity fully verified. Say only: Thank you.'
            S('identity_state', 'verified')
        elif hint and hint in hints:
            msg = str(hints[hint]) + ' Then call verify_identity again with the corrected answer.'
        elif hint:
            msg = 'The service returned the hint ' + str(hint) + '. Ask for this answer again, more precisely.'
        elif str(d.get(R.get('ok') or 'ok')).lower() == 'false' and not good:
            msg = 'The answer could not be read (' + str(d.get('error') or 'unreadable') + '). This did NOT count as a wrong answer. Ask the customer to repeat it clearly, for example a date with the month as a word.'
        elif good:
            msg = ('Correct. Now ask the next question: ' + nxt[0].get('ask')) if nxt else 'Correct. Say only: Thank you.'
            if nxt:
                S('id_field_now', nxt[0].get('field'))
        else:
            try:
                n_left = int(left)
            except Exception:
                n_left = None
            if n_left is not None and n_left <= 0:
                msg = 'Wrong answer and no attempts are left. The security check FAILED. Do not ask anything else and say nothing about any account.'
                S('identity_state', 'failed')
            else:
                msg = 'That answer is WRONG. Tell the customer it does not match and ask the same question again: ' + str(cur_ask) + (' (' + str(n_left) + ' wrong answers left in total)' if n_left is not None else '')
        d['what_to_do_next'] = msg
except Exception:
    pass
'''

PROMISE_PRE = LIB + r'''
try:
    P = DATA.get('promise_tool') or dict()
    b = config.get('body')
    S('promise_block', '')
    if isinstance(b, dict):
        plist = products()
        pk, ak, dk = P.get('product_param') or 'product_id', P.get('amount_param') or 'amount', P.get('date_param') or 'date'
        pid = str(b.get(pk) or '').strip()
        ids = [p['product_id'] for p in plist]
        if pid not in ids:
            m = re.findall(r'\d+', pid)
            if len(plist) == 1:
                pid = ids[0]
            elif m and 1 <= int(m[0]) <= len(plist):
                pid = ids[int(m[0]) - 1]
            else:
                for p in plist:
                    if p['type'] and p['type'].replace('_', ' ') in pid.replace('_', ' ').lower():
                        pid = p['product_id']
            b[pk] = pid
        prod = [p for p in plist if p['product_id'] == pid]
        d = parse_date(b.get(dk), 'DMY')
        if d:
            b[dk] = d.isoformat()
        amt = num(b.get(ak))
        if amt is not None:
            b[ak] = round(amt, 2)
        today = now_dt().date()
        why = ''
        if prod:
            p = prod[0]
            dl = datetime.date.fromisoformat(p['deadline'])
            if d is None:
                why = 'the date could not be read; send it as YYYY-MM-DD'
            elif d < today:
                why = 'the date ' + d.isoformat() + ' is in the past'
            elif d > dl:
                why = 'the date ' + d.isoformat() + ' is after the deadline ' + iso_say(dl) + '. Offer the deadline instead'
            elif not is_bd(d):
                why = d.isoformat() + ' is not a business day. Offer the next business day, ' + iso_say(bd_on_or_after(d))
            elif amt is None:
                why = 'the amount could not be read'
            elif amt > float(p['full']) + 0.005:
                why = 'the amount ' + money(amt) + ' is more than the past-due amount ' + money(p['full'])
            elif amt < float(p['floor']) - 0.005:
                why = 'the amount ' + money(amt) + ' is below the floor ' + money(p['floor']) + '. Say it cannot be recorded and offer the floor'
            done = [x for x in str(V('promised_ids', '') or '').split(',') if x]
            if not why and pid in done:
                why = 'a promise for this product is already recorded. It cannot be changed in this call'
        if why:
            S('promise_block', why)
            b['customer_id'] = 'blocked-by-agent-policy'
        S('promise_last_pid', pid)
except Exception:
    pass
'''

PROMISE_POST = LIB + r'''
try:
    P = DATA.get('promise_tool') or dict()
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if not isinstance(d, dict):
            d = dict()
            result['data'] = d
        block = str(V('promise_block', '') or '')
        pid = str(V('promise_last_pid', '') or '')
        ok = str(d.get(P.get('ok_field') or 'ok')).lower() == 'true' and not block
        plist = products()
        if block:
            d['ok'] = False
            d['error'] = 'not allowed by the bank rules'
            d['what_to_do_next'] = 'NOTHING was recorded, because ' + block + '. Do not say it is recorded. Tell the customer and propose a valid option, then read it back and ask for confirmation again.'
        elif ok:
            done = [x for x in str(V('promised_ids', '') or '').split(',') if x]
            if pid and pid not in done:
                done.append(pid)
            S('promised_ids', ','.join(done))
            S('promises_recorded', str(len(done)))
            left = [p for p in plist if p['product_id'] not in done]
            S('promises_all', 'yes' if not left else 'no')
            if left:
                d['what_to_do_next'] = 'The promise IS recorded. Next: call create_promise for the next agreed product, or ' + ('add_note for each product without a promise, ' if (DATA.get('notes') or dict()).get('enabled') else '') + 'then call the end tool. Do not say goodbye.'
            else:
                d['what_to_do_next'] = 'The promise IS recorded. Say nothing more: the closing words are spoken automatically.'
        else:
            k = 'promise_fail_' + re.sub(r'\W', '_', pid)
            n = int(num(V(k, '0')) or 0) + 1
            S(k, str(n))
            if n < 2:
                d['what_to_do_next'] = 'The bank system FAILED and nothing was recorded. Do not say it is recorded. Call create_promise again right now with exactly the same values.'
            else:
                S('promise_failed_ids', ','.join([x for x in str(V('promise_failed_ids', '') or '').split(',') if x] + [pid]))
                d['what_to_do_next'] = 'The bank system failed again. Nothing was recorded for this product. Tell the customer you could not record the promise.'
except Exception:
    pass
'''

CALLBACK_PRE = LIB + r'''
try:
    cb = DATA.get('callback') or dict()
    b = config.get('body')
    S('callback_block', '')
    if isinstance(b, dict):
        n = now_dt()
        today = n.date()
        DP, TP = cb.get('date_param') or 'date', cb.get('time_param') or 'time'
        d = parse_date(b.get(DP), 'DMY')
        if d:
            b[DP] = d.isoformat()
        t = str(b.get(TP) or '').strip().lower()
        m = re.match(r'^(\d{1,2})(?::|\.|h)?(\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?', t)
        if m:
            hh = int(m.group(1)); mm = int(m.group(2) or 0)
            if m.group(3) and m.group(3).startswith('p') and hh < 12:
                hh += 12
            b[TP] = '%02d:%02d' % (hh, mm)
        allowed = [today]
        if cb.get('days') == 'today_or_next_business_day':
            allowed = [today, next_bd(today)]
        elif cb.get('days') == 'next_business_day':
            allowed = [next_bd(today)]
        elif cb.get('days') == 'today_only':
            allowed = [today]
        tt = str(b.get(TP) or '')
        why = ''
        if d not in allowed:
            why = 'the day is outside the allowed callback days'
        elif not (str(cb.get('window_start') or '00:00') <= tt <= str(cb.get('window_end') or '23:59')):
            why = 'the time is outside ' + str(cb.get('window_start')) + ' to ' + str(cb.get('window_end'))
        elif d == today and cb.get('must_be_after_now', True) and tt <= (n + datetime.timedelta(minutes=int(cb.get('min_minutes_after_now') or 0))).strftime('%H:%M'):
            why = 'the time is too soon after now'
        if why:
            S('callback_block', why)
            b['customer_id'] = 'blocked-by-agent-policy'
except Exception:
    pass
'''

CALLBACK_POST = LIB + r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if not isinstance(d, dict):
            d = dict()
            result['data'] = d
        block = str(V('callback_block', '') or '')
        if block:
            d['ok'] = False
            n = int(num(V('callback_rejections', '0')) or 0) + 1
            S('callback_rejections', str(n))
            d['what_to_do_next'] = 'NOT scheduled: ' + block + '. ' + ('Ask once for another time inside the allowed window.' if n < 2 else 'Do not schedule. End the call as no_callback.')
        elif str(d.get('ok')).lower() == 'true':
            S('callback_state', 'scheduled')
            d['what_to_do_next'] = 'The callback is scheduled. Say thank you and goodbye.'
        else:
            d['what_to_do_next'] = 'The callback could not be scheduled (' + str(d.get('error') or 'error') + '). Try once more.'
except Exception:
    pass
'''

TRANSFER_POST = LIB + r'''
try:
    T = DATA.get('transfer') or dict()
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if not isinstance(d, dict):
            d = dict()
            result['data'] = d
        if str(d.get('ok')).lower() == 'true':
            S('transfer_done_queue', str(V('transfer_last_queue', '') or ''))
            d['what_to_do_next'] = 'The transfer is done. Say goodbye.'
        else:
            d['what_to_do_next'] = 'The transfer failed (' + str(d.get('error') or 'error') + '). Call transfer_to_agent once more.'
except Exception:
    pass
'''

TRANSFER_PRE = LIB + r'''
try:
    b = config.get('body')
    if isinstance(b, dict):
        S('transfer_last_queue', str(b.get(__QPARAM__) or ''))
except Exception:
    pass
'''

NOTE_PRE = LIB + r'''
try:
    conv = ''
    h = config.get('headers')
    if isinstance(h, dict):
        conv = str(h.pop('X-Conversation', '') or '')
    S('note_block', '')
    b = config.get('body')
    if isinstance(b, dict):
        pid, reason = str(b.get(__PPARAM__) or ''), str(b.get(__RPARAM__) or '')
        S('note_last', pid + '|' + reason)
        if (DATA.get('notes') or dict()).get('none_on_transfer') and str(V('transfer_done_queue', '') or ''):
            S('note_block', 'the call was transferred, and no notes are written on a transferred call. Do not call add_note again; the call ends now.')
            b['customer_id'] = 'blocked-by-agent-policy'
        # A 'refused' note is only allowed after every offer of the product's sequence was made.
        rows = [r for r in (DATA.get('outcomes') or []) if (r.get('reason') or '') == reason]
        checked = [x for x in str(V('note_checked', '') or '').split(',') if x]
        if rows and rows[0].get('role') == 'refused' and conv and not conv.startswith('{' + '{') and pid not in checked:
            agent = agent_text(conv)
            prod = [p for p in products() if p['product_id'] == pid]
            missing = None
            for o in (prod[0].get('offers') or []) if prod else []:
                d = datetime.date.fromisoformat(o['date'])
                day = str(d.day)
                said_date = (MONTHS[d.month - 1] in agent and re.search(r'\b' + day + r'(st|nd|rd|th)?\b', agent)) or d.isoformat() in agent
                said_amt = any(money(x).split(' ')[0].lower() in agent for x in o['amounts'])
                if not (said_date and said_amt):
                    missing = o
                    break
            if missing:
                S('note_checked', ','.join(checked + [pid]))
                S('note_block', 'offer ' + str(missing['number']) + ' for the ' + prod[0]['spoken'] + ' was not made yet. Say exactly: "' + missing['text'] + '" If the customer refuses it too, call add_note again.')
                b['customer_id'] = 'blocked-by-agent-policy'
except Exception:
    pass
'''

NOTE_POST = LIB + r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if not isinstance(d, dict):
            d = dict()
            result['data'] = d
        block = str(V('note_block', '') or '')
        if block:
            d['ok'] = False
            d['what_to_do_next'] = 'NOT saved: ' + block
        elif str(d.get('ok')).lower() == 'true':
            pid, reason = (str(V('note_last', '|') or '|').split('|') + [''])[:2]
            notes = json.loads(V('notes_json', '[]') or '[]')
            notes = [x for x in notes if x[0] != pid] + [[pid, reason]]
            S('notes_json', json.dumps(notes))
            d['what_to_do_next'] = 'The note is saved. Continue with the next product, or close the call if every product is handled.'
        else:
            d['what_to_do_next'] = 'The note failed (' + str(d.get('error') or 'error') + '). Call add_note once more.'
except Exception:
    pass
'''

CLOSE_PRE = r'''
import json
try:
    b = config.get('body')
    if isinstance(b, dict):
        o = str(b.get(__OPARAM__) or '')
        r = str(b.get(__RPARAM__) or '')
        if o in __NOREASON__ or not r or r.startswith('{'):
            b.pop(__RPARAM__, None)
except Exception:
    pass
'''

GENERIC_POST = r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
except Exception:
    pass
'''


def embed(obj):
    """A Python expression that rebuilds `obj`, with no brace characters in the source."""
    lit = json.dumps(json.dumps(obj, ensure_ascii=True))
    lit = lit.replace("{", "\\x7b").replace("}", "\\x7d")
    return "json.loads(" + lit + ")"


def pystr(s):
    return embed(s)


def fill(code, data, **subs):
    code = code.replace("__DATA__", embed(data))
    for k, v in subs.items():
        code = code.replace("__" + k + "__", v)
    check_code(code)
    return code


def check_code(code):
    if "{{" in code or "}}" in code:
        raise ValueError("generated code contains a double brace")
    body = "def _wrapped(vars, params):\n" + "\n".join("    " + ln for ln in code.split("\n"))
    compile(body if "\nreturn " in code else code, "<snippet>", "exec")

END_PATH = r'''
import json
try:
    vars['end_path_outcome'] = __OUTCOME__
    vars['end_path_reason'] = __REASON__
    vars['end_path_role'] = __ROLE__
except Exception:
    pass
'''

# --- check_payment: a code tool the phone agent calls whenever the customer names a day or an amount ----------
# The platform wraps the code in a function: arguments arrive in `params`, and what the code returns is the tool
# result the model reads. Dates are read from the customer's own words, relative to the call's `now`.
CHECK_PAYMENT = LIB + r'''
ORD = dict(first=1, second=2, third=3, fourth=4, fifth=5, sixth=6, seventh=7, eighth=8, ninth=9, tenth=10, eleventh=11,
           twelfth=12, thirteenth=13, fourteenth=14, fifteenth=15, sixteenth=16, seventeenth=17, eighteenth=18, nineteenth=19,
           twentieth=20, thirtieth=30)
UNITS = dict(one=1, two=2, three=3, four=4, five=5, six=6, seven=7, eight=8, nine=9)
WD = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

CARD = dict(one=1, two=2, three=3, four=4, five=5, six=6, seven=7, eight=8, nine=9, ten=10, eleven=11, twelve=12,
            thirteen=13, fourteen=14, fifteen=15, sixteen=16, seventeen=17, eighteen=18, nineteen=19, twenty=20, thirty=30)

def words_to_digits(t):
    # 'twenty-sixth' / 'twenty six' / 'thirty first' -> 26 / 26 / 31; then single ordinal and cardinal words
    units = [(w, n) for w, n in list(ORD.items()) + list(CARD.items()) if n < 10]
    for tens, base in (('twenty', 20), ('thirty', 30)):
        for w, n in units:
            t = re.sub(r'\b' + tens + r'[\s-]+' + w + r'\b', str(base + n), t)
    for w, n in sorted(list(ORD.items()) + list(CARD.items()), key=lambda x: -len(x[0])):
        t = re.sub(r'\b' + w + r'\b', str(n), t)
    return t

def spoken_day(text, today, next_rule):
    """(date or None, note). Reads 'Monday the 26th', 'next Friday', 'tomorrow', '30 October', '2026-10-27'."""
    t = ' ' + str(text or '').lower().replace(',', ' ').replace('.', ' ') + ' '
    parts = re.split(r'\b(?:i mean|sorry|actually|rather|correction|no wait|make that|or rather)\b', t)
    if len(parts) > 1 and parts[-1].strip():
        t = ' ' + parts[-1] + ' '        # the customer corrected themselves: the last version counts
    if re.search(r'\d{4}-\d{2}-\d{2}', t):
        return parse_date(re.search(r'\d{4}-\d{2}-\d{2}', t).group(0), 'DMY'), ''
    t = words_to_digits(t)
    if 'day after tomorrow' in t:
        return today + datetime.timedelta(days=2), ''
    if 'tomorrow' in t:
        return today + datetime.timedelta(days=1), ''
    if re.search(r'\b(today|now|right away)\b', t):
        return today, ''
    mo = None
    for i, name in enumerate(MONTHS):
        if re.search(r'\b(' + name + '|' + name[:3] + r')\b', t):
            mo = i + 1
    num = re.search(r'\b(\d{1,2})(st|nd|rd|th)?\b', t)
    wd = None
    for i, name in enumerate(WD):
        if re.search(r'\b' + name + r'\b', t):
            wd = i
    if num:
        day = int(num.group(1))
        cands = []
        for k in range(0, 13):
            y, m = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
            if mo and m != mo:
                continue
            try:
                d = datetime.date(y, m, day)
            except Exception:
                continue
            if d >= today or (mo and k == 0):
                cands.append(d)   # a named month this year that is already past stays in the past (it is not next year)
        if cands:
            note = ''
            if wd is not None and cands[0].weekday() != wd:
                note = 'The customer said ' + WD[wd].capitalize() + ' but the ' + str(day) + ' is a ' + WEEKDAYS[cands[0].weekday()] + '; check which day they mean.'
            return cands[0], note
    if wd is not None:
        monday = today - datetime.timedelta(days=today.weekday())
        if re.search(r'\bnext\b', t) and next_rule != 'next_occurrence':
            return monday + datetime.timedelta(days=7 + wd), ''
        if re.search(r'\bthis\b', t):
            d = monday + datetime.timedelta(days=wd)
            if d >= today:
                return d, ''
        d = today + datetime.timedelta(days=1)
        while d.weekday() != wd:
            d = d + datetime.timedelta(days=1)
        return d, ''
    return None, 'vague'

CALP = DATA.get('calendar') or dict()

def check(params):
    n = now_dt()
    today = n.date()
    plist = products()
    if not plist:
        return dict(what_to_do_next='No account facts are loaded. Continue with the conversation.')
    want = str(params.get('product') or '').strip().lower()
    chosen = []
    for p in plist:
        if want and (want == p['product_id'].lower() or want == str(p['index']) or want in p['spoken'].lower() or p['type'].replace('_', ' ') in want):
            chosen.append(p)
    if not chosen:
        chosen = plist
    out = []
    day_text = str(params.get('day') or '').strip()
    d, note = (None, '')
    if day_text:
        d, note = spoken_day(day_text, today, (DATA.get('calendar') or dict()).get('next_weekday_rule') or 'following_week')
    amt = num(params.get('amount')) if str(params.get('amount') or '').strip() else None
    for p in chosen:
        dl = datetime.date.fromisoformat(p['deadline'])
        who = (p['spoken'] + ': ') if len(chosen) > 1 else ''
        if day_text:
            if d is None:
                if re.search(r'\d|' + '|'.join(MONTHS), words_to_digits(day_text.lower())):
                    out.append(who + 'the day could not be read. Ask the customer to say it as day and month, for example the 23rd of October.')
                else:
                    out.append(who + 'no exact day was named (a vague period). Apply the rule for vague periods; the latest date you can record is ' + say_date(dl) + '.')
            elif d < today:
                out.append(who + say_date(d) + ' is in the past. Ask for a day from today on.')
            elif d > dl:
                if CALP.get('after_deadline') == 'refuse':
                    out.append(who + say_date(d) + ' is after the latest date that can be recorded (' + say_date(dl) + '). It cannot be recorded; apply the rules for dates after the deadline.')
                else:
                    out.append(who + say_date(d) + ' is after the deadline. Say the latest date you can record is ' + say_date(dl) + ' and offer ' + say_date(dl) + '.')
            elif not is_bd(d):
                why = 'a holiday' if d.isoformat() in HOL else 'not a business day'
                if CALP.get('non_business_day') == 'previous_business_day':
                    nb = d - datetime.timedelta(days=1)
                    while not is_bd(nb):
                        nb = nb - datetime.timedelta(days=1)
                    if nb < today:
                        nb = bd_on_or_after(today)
                    out.append(who + say_date(d) + ' is ' + why + '. Offer the previous business day, ' + say_date(nb) + ' (' + nb.isoformat() + ').')
                elif CALP.get('non_business_day') == 'refuse':
                    out.append(who + say_date(d) + ' is ' + why + ' and cannot be recorded. Ask for a business day.')
                else:
                    nb = bd_on_or_after(d)
                    if nb > dl:
                        nb = dl
                    out.append(who + say_date(d) + ' is ' + why + '. Offer the next business day, ' + say_date(nb) + ' (' + nb.isoformat() + ').')
            else:
                out.append(who + say_date(d) + ' (' + d.isoformat() + ') is fine and can be recorded.')
        if amt is not None:
            if amt > float(p['full']) + 0.005:
                out.append(who + 'the amount ' + money(amt) + ' is more than the past-due amount ' + money(p['full']) + '; the most you can record is ' + money(p['full']) + '.')
            elif amt < float(p['floor']) - 0.005:
                out.append(who + 'the amount ' + money(amt) + ' is below the lowest amount that can be recorded. Say it cannot be recorded and offer the ' + p['floor_name'] + ' of ' + money(p['floor']) + ' once.')
            else:
                out.append(who + 'the amount ' + money(amt) + ' is acceptable and can be recorded.')
    if note and note != 'vague':
        out.append(note)
    msg = ' '.join(out) or 'Nothing to check.'
    if all(('can be recorded' in x and 'cannot' not in x) or 'acceptable' in x for x in out) and out:
        msg += ' Now say your next sentence to the customer: if the day and the amount are agreed, read back the product, the amount and the date and ask for confirmation; otherwise propose what is still missing.'
    else:
        msg += ' Now say this to the customer in one or two short sentences.'
    return dict(day=(d.isoformat() if d else ''), what_to_do_next=msg)

try:
    _r = check(params if isinstance(params, dict) else dict())
except Exception as e:
    _r = dict(what_to_do_next='The check failed (' + str(e)[:80] + '). Use the DATE LOOKUP in the facts.')
S('last_check', _r.get('what_to_do_next', ''))
return _r
'''

# --- deterministic identity path ---------------------------------------------------------------------------------
# The extraction model writes the customer's answer into `id_answer`; these code nodes check that it is complete,
# let the engine call verify_identity (node id_check), and turn the result into the exact next sentence (id_say_text).
ID_PREP = LIB + r'''
try:
    I = DATA.get('identity') or dict()
    qs = I.get('questions') or []
    okset = [x for x in str(V('id_ok_fields', '') or '').split(',') if x]
    f = str(V('id_field_now', '') or '') or ([q.get('field') for q in qs if q.get('field') not in okset] + [''])[0]
    q = ([x for x in qs if x.get('field') == f] + [dict()])[0]
    ans = str(V('id_answer', '') or '').strip()
    S('id_answer', '')
    fmt = q.get('answer_format') or 'text'
    norm, missing = '', ''
    if fmt == 'date':
        d = parse_date(ans, I.get('numeric_date_order') or 'DMY')
        if d is None or not re.search(r'\d{4}|\d{1,2}[./-]\d{1,2}[./-]\d{2}', ans) or d.year > now_dt().year - 10:
            missing = 'the full date including the year'
        else:
            norm = d.isoformat()
    elif fmt in ('digits', 'year'):
        ds = re.sub(r'\D', '', ans)
        need = int(q.get('digits') or (4 if fmt == 'year' else 0))
        if need and len(ds) < need:
            missing = 'all ' + str(need) + ' digits'
        else:
            norm = ds[-need:] if need else ds
    else:
        norm = ans
        if not norm:
            missing = 'the answer'
    last = str(V('id_last_' + f, '') or '')
    if missing:
        S('id_route', 'ask')
        S('id_say_text', 'Thank you. Could you please give me ' + missing + '?')
    elif norm == last:
        S('id_route', 'ask')
        S('id_say_text', str(q.get('ask') or 'Could you please repeat your answer?'))
    else:
        S('id_route', 'check')
        S('id_submit_field', f)
        S('id_submit_answer', norm)
        S('id_last_' + f, norm)
except Exception as e:
    S('id_route', 'ask')
    S('id_say_text', 'Could you please repeat your answer?')
'''

ID_AFTER = LIB + r'''
try:
    I = DATA.get('identity') or dict()
    R = I.get('response') or dict()
    qs = I.get('questions') or []
    pre = 'id_check_response.data.'
    def g(k):
        return V(pre + str(k), None)
    f = str(V('id_submit_field', '') or '')
    okset = [x for x in str(V('id_ok_fields', '') or '').split(',') if x]
    good = str(g(R.get('answer_ok') or 'verified')).lower() == 'true'
    allok = str(g(R.get('all_ok') or 'all_verified')).lower() == 'true'
    hint = g(R.get('hint') or 'hint')
    left = g(R.get('remaining') or 'wrong_answers_left')
    okflag = str(g(R.get('ok') or 'ok')).lower()
    if good and f and f not in okset:
        okset.append(f)
        S('id_ok_fields', ','.join(okset))
    nxt = [x for x in qs if x.get('field') not in okset]
    cur = ([x for x in qs if x.get('field') == f] + [dict()])[0]
    S('id_say_text', '')
    if allok or (good and not nxt):
        S('identity_state', 'verified')
    elif hint and str(hint) not in ('None', 'null', ''):
        S('id_last_' + f, '')
        S('id_say_text', 'I am sorry, could you please say it once more, with the month as a word?' if 'month' in str(dict((h.get('value'), h.get('instruction')) for h in I.get('hints') or []).get(hint, '')).lower() else 'I am sorry, could you please repeat that?')
    elif okflag == 'false' and not good:
        S('id_last_' + f, '')
        S('id_say_text', 'I am sorry, I could not catch that. ' + str(cur.get('ask') or ''))
    elif good:
        S('id_field_now', nxt[0].get('field'))
        S('id_say_text', 'Thank you. ' + str(nxt[0].get('ask') or ''))
    else:
        try:
            n_left = int(left)
        except Exception:
            n_left = None
        if n_left is not None and n_left <= 0:
            S('identity_state', 'failed')
        else:
            S('id_say_text', 'I am sorry, that does not match our records. ' + str(cur.get('ask') or ''))
except Exception as e:
    S('id_say_text', 'Could you please repeat your answer?')
'''
