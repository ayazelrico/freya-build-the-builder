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
                if n.strftime('%H:%M') >= end:
                    continue
                if n.strftime('%H:%M') >= start:
                    lo = 'after ' + n.strftime('%H:%M')
            lines.append(say_date(d) + ' (' + d.isoformat() + '), ' + lo + ' to ' + end)
        S('callback_window', '; or '.join(lines) if lines else 'none')
        tomorrow = today + datetime.timedelta(days=1)
        S('callback_facts', 'Allowed callback times: ' + V('callback_window', '') + '. Tomorrow is ' + say_date(tomorrow) + ' (' + tomorrow.isoformat() + ').')
    S('today_iso', today.isoformat())
    S('today_facts', ' '.join(facts))
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
        if floor is None or (full is not None and floor > full):
            floor = full
        b = band_for(days)
        dl = deadline_for(b, today)
        att = int(b.get('attempts') or 1)
        plan = []
        for a in (DATA.get('attempts') or [])[:att]:
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
    intro = L.get('debt_intro_multi' if multi else 'debt_intro') or L.get('debt_intro') or ''
    ask = L.get('first_ask_multi' if multi else 'first_ask') or L.get('first_ask') or ''
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
        for a in p['plan']:
            ad = datetime.date.fromisoformat(a['date'])
            rule = a['amount_rule'] or 'full'
            if rule == 'floor':
                amt = 'the floor ' + money(p['floor'])
            elif rule == 'full_or_floor_if_full_refused':
                amt = 'the full ' + money(p['full']) + ' (or the floor ' + money(p['floor']) + ' if they already said the full amount is too much)'
            else:
                amt = 'the full ' + money(p['full'])
            F.append('- Persuasion attempt ' + str(a['number']) + ': propose ' + amt + ' on ' + iso_say(ad) + '.')
    # Calendar table from today to the latest deadline plus a margin.
    last = max([datetime.date.fromisoformat(p['deadline']) for p in plist] or [today]) + datetime.timedelta(days=10)
    F.append('')
    F.append('CALENDAR (use it for every date the customer names):')
    d = today
    while d <= last:
        tag = 'business day'
        if not is_bd(d):
            why = 'holiday' if d.isoformat() in HOL else 'weekend'
            tag = 'NOT a business day (' + why + '), next business day is ' + say_date(next_bd(d)) + ' ' + next_bd(d).isoformat()
        late = [str(p['index']) for p in plist if d > datetime.date.fromisoformat(p['deadline'])]
        if late:
            tag += '; AFTER THE DEADLINE of product ' + ', '.join(late)
        F.append('- ' + say_date(d) + ' = ' + d.isoformat() + ': ' + tag)
        d = d + datetime.timedelta(days=1)
    S('negotiation_facts', '\n'.join(F))
    S('account_state', 'loaded' if plist else 'empty')
except Exception as e:
    S('account_state', 'error')
    S('negotiation_facts', 'The account could not be read.')
    S('debt_statement', '')
    S('compute_error', str(e)[:200])
'''

# End of call: decide the final outcome and the farewell line from the end path taken (end_path_outcome / end_path_reason).
END = LIB + r'''
try:
    L = DATA.get('lines') or dict()
    outcome, reason = str(V('end_path_outcome', '') or ''), str(V('end_path_reason', '') or '')
    q2r = (DATA.get('transfer') or dict()).get('queue_to_reason') or dict()
    tq = str(V('transfer_done_queue', '') or '')
    rec = int(num(V('promises_recorded', '0')) or 0)
    if tq:
        outcome, reason = 'transferred', q2r.get(tq, tq)
    elif rec > 0:
        outcome, reason = 'promise', ''
    elif (DATA.get('notes') or dict()).get('enabled') and outcome in ('no_promise', 'paid', 'promise'):
        notes = []
        try:
            notes = json.loads(V('notes_json', '[]') or '[]')
        except Exception:
            notes = []
        if notes:
            order = [p['product_id'] for p in products()]
            notes.sort(key=lambda x: order.index(x[0]) if x[0] in order else 99)
            nonpaid = [x for x in notes if x[1] != 'paid']
            if not nonpaid:
                outcome, reason = 'paid', ''
            else:
                outcome, reason = 'no_promise', nonpaid[0][1]
    words = []
    if outcome == 'promise':
        words += [L.get('promise_recorded') or '', L.get('sms_sentence') or '']
    elif outcome == 'paid':
        words += [L.get('already_paid') or '']
    elif reason == 'deceased':
        words += [L.get('condolence') or '']
    elif outcome == 'not_verified' and reason == 'failed':
        words += [L.get('identity_failed') or '']
    elif reason == 'service_error':
        words += [L.get('service_error') or '']
    words += [L.get('goodbye') or 'Goodbye.']
    S('farewell_text', ' '.join([w for w in words if w]))
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
            d['what_to_do_next'] = 'The promise IS recorded. ' + ('Call create_promise for the next agreed product now.' if left else 'Tell the customer it is recorded.')
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
        d = parse_date(b.get('date'), 'DMY')
        if d:
            b['date'] = d.isoformat()
        t = str(b.get('time') or '').strip().lower()
        m = re.match(r'^(\d{1,2})(?::|\.|h)?(\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?', t)
        if m:
            hh = int(m.group(1)); mm = int(m.group(2) or 0)
            if m.group(3) and m.group(3).startswith('p') and hh < 12:
                hh += 12
            b['time'] = '%02d:%02d' % (hh, mm)
        allowed = [today]
        if cb.get('days') == 'today_or_next_business_day':
            allowed = [today, next_bd(today)]
        elif cb.get('days') == 'next_business_day':
            allowed = [next_bd(today)]
        tt = str(b.get('time') or '')
        why = ''
        if d not in allowed:
            why = 'the day is outside the allowed callback days'
        elif not (str(cb.get('window_start') or '00:00') <= tt <= str(cb.get('window_end') or '23:59')):
            why = 'the time is outside ' + str(cb.get('window_start')) + ' to ' + str(cb.get('window_end'))
        elif d == today and cb.get('must_be_after_now', True) and tt <= n.strftime('%H:%M'):
            why = 'the time is not later than now'
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
    b = config.get('body')
    if isinstance(b, dict):
        S('note_last', str(b.get(__PPARAM__) or '') + '|' + str(b.get(__RPARAM__) or ''))
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
        if str(d.get('ok')).lower() == 'true':
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
    compile(code, "<snippet>", "exec")

END_PATH = r'''
import json
try:
    vars['end_path_outcome'] = __OUTCOME__
    vars['end_path_reason'] = __REASON__
except Exception:
    pass
'''
