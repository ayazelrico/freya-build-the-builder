# SPEC schema

The builder turns a bank brief (clean specification or raw bank material: mails, policy extracts,
memos that change earlier rules, code lists) into ONE JSON object with exactly these keys.
Code turns the SPEC into a phone-agent workflow, so every value must be exact.

General rules
- Take every value from the brief and the tool API file. Never invent a rule or a value.
- When a later memo or note changes a rule, use the changed rule only.
- Sentences in `lines` are spoken word for word by the phone agent. Code adds the product details after debt_intro, so debt_intro names no product or amount. The only placeholders allowed are call variables such as {title} and {last_name}, plus {amount}, {date} and {floor_name} in full_offer and floor_offer.
- Sentences in `lines` are spoken word for word by the phone agent. Write them in the call language,
  short, polite, and containing exactly what the brief requires to be said. `{name}` inserts a call variable.
- Tool parameter names, enum values, response field names: copy them exactly from the tool API file.

```jsonc
{
  "bank_name": "Example Bank",
  "language": "English",
  "currency_word": "",                 // spoken after amounts, "" if the brief names no currency
  "call_variables": ["customer_id", "first_name", "last_name", "title", "now"],   // variables every call starts with

  "lines": {
    "opening": "...",                  // first sentence (who calls, recorded, ...). Must not reveal the reason before verification.
                                       // Say a recording notice as "We record this call." - never the word "recorded",
                                       // which a reviewer reads as a claim that a promise was saved
    "confirm_identity": "Am I speaking with {title} {last_name}?",
    "ai_answer": "...",                // answer when asked "are you a robot"
    "scam_answer": "...",              // answer when asked "is this a scam"
    "identity_intro": "...",           // said right before the first security question, after the person confirmed
    "identity_failed": "...",          // said when the identity check failed (e.g. go to app/branch)
    "identity_decline_explanation": "...",
    "debt_intro": "...",               // after verification, single product: who is calling and why
    "debt_intro_multi": "...",         // same for several products
    "first_ask": "...",                // first question after stating the debt (single product)
    "first_ask_multi": "...",          // same for several products
    "full_offer": "Can you pay the full {amount} on {date}?",            // a persuasion offer of the full amount
    "floor_offer": "...{floor_name}...{amount}...{date}...",           // an offer of the floor amount, with every sentence the brief requires
                                                                        // when the floor is offered (e.g. that the rest stays overdue)
    "confirm_question": "Do you confirm?",
    "promise_recorded": "...",         // said only after the promise tool succeeded
    "sms_sentence": "...",             // any sentence the brief requires after a recorded promise, "" if none
    "service_error": "...",            // the promise could not be recorded
    "already_paid": "...",             // what to say when the customer says they already paid
    "change_promise": "...",
    "condolence": "...",               // when the customer has died
    "no_info": "...",
    "goodbye": "..."                   // closing thanks + goodbye
  },
  "forbidden_before_verification": ["..."],   // words/topics never said before identity is verified

  "contact": { "max_asks": 2, "confirmations": ["..."], "not_confirmations": ["..."] },

  "callback": {                        // when someone else answers
    "enabled": true,
    "days": "today_or_next_business_day",   // one of: today_only, next_business_day, today_or_next_business_day
    "window_start": "HH:MM", "window_end": "HH:MM",    // inclusive
    "must_be_after_now": true,
    "min_minutes_after_now": 0,        // e.g. 60 when the callback must be at least one hour after now
    "max_asks": 2
  },

  "identity": {
    "field_param": "field",            // verify tool parameter that names the question
    "answer_param": "answer",          // verify tool parameter with the answer
    "questions": [                     // in the order the brief requires
      {"field": "<enum value from the tool API>", "ask": "<question to say>", "answer_format": "date|digits|year|text", "digits": 4, "spoken_name": "..."}
    ],
    "max_wrong_total": 3,
    "numeric_date_order": "DMY",       // how to read a date given only as numbers: DMY or MDY
    "response": {"answer_ok": "<bool field: this answer correct>", "all_ok": "<bool field: all passed>", "remaining": "<int field: wrong answers left>", "hint": "<hint field>", "ok": "ok"},
    "hints": [{"value": "<hint value>", "instruction": "<what the agent says/does>"}],
    "decline_max": 2
  },

  "account": {"products_field": "products", "id_field": "product_id", "type_field": "type", "past_due_field": "past_due", "days_late_field": "days_late"},

  "product_types": {                   // one entry per product type value in the tool API
    "<type value>": {"spoken": "credit card ending {card_last4}", "floor_field": "<field holding the lowest acceptable amount>", "floor_name": "minimum payment"}
  },                                   // {field} in "spoken" inserts a field of the product record

  "calendar": {"business_weekdays": [1,2,3,4,5], "holidays": ["YYYY-MM-DD"],      // ISO weekday numbers, Monday = 1
               "next_weekday_rule": "following_week"},   // "next Friday" = Friday of the following calendar week (following_week)
                                                         // or the next Friday to come (next_occurrence); following_week if the brief is silent

  "bands": [                           // how late -> deadline and number of persuasion attempts
    {"name": "...", "min_days_late": 1, "max_days_late": 10,
     "deadline": {"type": "business_days_after_today", "n": 5},
     "attempts": 1}
  ],
  // deadline types: business_days_after_today (the n-th business day after today),
  //   business_days_after_today_counting_today, calendar_days_after_today (rolled back to a business day),
  //   end_of_month, end_of_next_month, fixed_date (with "date")

  "attempts": [                        // persuasion attempts in order; a band uses the first `attempts` of them
    {"number": 1, "amount": "full|floor|full_or_floor_if_full_refused", "date": "<date rule>"}
  ],
  // date rules: last_business_day_this_week_or_next_if_today, last_business_day_this_week,
  //   next_business_day, today, deadline, business_days_after_today:<n>

  "promise_tool": {"product_param": "product_id", "amount_param": "amount", "date_param": "date", "ok_field": "ok"},
  "multi_product": false,              // true when a customer can have several products
  "notes": {"enabled": false, "tool": "add_note", "product_param": "product_id", "reason_param": "reason", "reasons": ["..."],
            "paid_reason": "<the note reason meaning 'already paid', or empty>",
            "none_on_transfer": false},      // true when the brief says no notes at all on a transferred call
  "transfer": {"queue_param": "queue", "queue_to_reason": {"<queue>": "<close reason used after this transfer>"}},
  "close": {"outcome_param": "outcome", "reason_param": "reason", "no_reason_outcomes": ["..."]},

  "outcomes": [                        // EVERY row of the brief's outcome table
    {"outcome": "<value>", "reason": "<value or empty>", "when": "<when, in a few words>",
     "stage": "contact|third_party|identity|negotiate|any", "role": "<one role from the list below>"}
  ],
  // role: what the row means, whatever the bank calls it. One of:
  //   promise (a payment promise/arrangement was recorded), paid (customer already paid),
  //   transferred (handed to a person/queue; one row per queue), refused (no promise: refused / attempts used up),
  //   hardship, dispute, service_error (the promise tool failed), id_failed (too many wrong security answers),
  //   id_declined (would not answer the security questions), callback (callback booked),
  //   no_callback (no valid callback time), wrong_number, deceased, unclear (could not tell who answered),
  //   other (anything else). Use each role for at most one row, except transferred.
  // stage: where in the call the outcome is decided. contact = before we know who is on the line
  //   (wrong number, unclear, deceased); third_party = someone else answered (callback...);
  //   identity = security questions; negotiate = after the debt was stated; any = can happen anywhere.

  "rules_text": {                      // the brief's rules for each step, as short imperative bullet lines ("- ...")
    "global": "...",                   // rules for the whole call (honesty, no invented terms, robot/scam questions, human requests)
    "contact": "...",                  // who is on the line
    "third_party": "...",              // someone else answered
    "identity": "...",                 // security questions
    "negotiate": "..."                 // stating the debt, dates, amounts, persuasion, special cases, confirmation, recording, multi-product rules
  }
}
```

`rules_text.negotiate` should read as a step-by-step procedure: the exact order of offers (amount and date of each), so that no offer is ever repeated.

`rules_text` must contain EVERY rule of the brief that applies in that step, including the numbers
(limits, windows, counts). It is the agent's only source for rules that the other fields do not cover.
Refer to tools by their names in the tool API file, and to call endings as "end as <reason>"
(or "end as <outcome>" when there is no reason).
