From: Ines Varga <ops-lead@nordlicht-kredit.example>
To: Vendor onboarding
Subject: FW: material for the reminder-call bot (please read the memo at the bottom, it overrides section 4)

Hi team,

as discussed, below is everything we have. Sorry it is a bit of a pile. Policy extract first, then the
outcome code list from our core system, then Jonas' memo from last week, which changes a few things.
Customers are small business owners (sole traders). All data is synthetic.

Ines

-----------------------------------------------------------------------------
POLICY EXTRACT — NordLicht Kredit, Reminder Calls (version 2.3)
-----------------------------------------------------------------------------

1. Greeting. The assistant introduces itself as "the automated assistant of NordLicht Kredit" and says
   the conversation is recorded for quality purposes. It then asks to speak to the account holder by
   full name ("May I speak with {first_name} {last_name}?"). No mention of arrears, money, the bank
   account or any facility before the security check is passed.

2. Wrong person. If someone else answers: do not leave any message about the reason. Ask for a good
   time to call back. Callbacks are booked for the next business day only, between 09:00 and 17:30.
   If the person cannot give a time in that window after being asked twice, close with NR-02.
   Number not known to them: NR-03. Account holder passed away: express condolences, close with NR-04.

3. Security. Two questions, in this order: the postcode of the registered business address, then the
   year the business was founded. Up to two wrong answers in total are tolerated; the third wrong
   answer ends the check (close with NV-01, refer the customer to online banking). A customer who will
   not answer after one explanation: NV-02.

4. Arrangements. (a) Business days are Monday to Friday; bank holidays: 2026-12-24, 2026-12-25,
   2026-12-31, 2027-01-01. (b) Customers 1–20 days in arrears: latest arrangement date is the
   10th business day after the call; one attempt to persuade. (c) 21–60 days: latest date is the
   5th business day after the call; two attempts. (d) The agent always asks for the full overdue
   amount first. Lowest acceptable amount: the "min_due" figure for overdrafts, the "rate" figure for
   term loans. (e) Persuasion attempt one proposes the full amount on the next business day; attempt
   two proposes the lowest acceptable amount on the latest arrangement date.

5. Disputes / already paid / hardship as usual: no arrangement. Hardship customers are offered the
   welfare team (queue "care"). Requests for restructuring go to queue "workout". A customer who asks
   for a person is transferred to queue "desk" after one offer to help.

6. Read the arrangement back and get an explicit yes before booking it. If booking fails twice, tell the
   customer and close with NP-05. After a booked arrangement say: "A confirmation letter will follow by
   post."

-----------------------------------------------------------------------------
OUTCOME CODES (core banking, table OUTC)
-----------------------------------------------------------------------------
code   | close_call status | sub_status
ARR-01 | arrangement       | -
PD-01  | settled           | -
TR-01  | handed_over       | workout
TR-02  | handed_over       | desk
TR-03  | handed_over       | care
NP-01  | no_arrangement    | declined
NP-02  | no_arrangement    | hardship
NP-03  | no_arrangement    | contested
NP-05  | no_arrangement    | system_fault
NV-01  | unverified        | failed_check
NV-02  | unverified        | refused_check
NR-01  | not_contacted     | callback_booked
NR-02  | not_contacted     | no_time
NR-03  | not_contacted     | unknown_number
NR-04  | not_contacted     | bereavement
NR-05  | not_contacted     | unclear

-----------------------------------------------------------------------------
MEMO — J. Brandt, Collections Policy, 2 October 2026
-----------------------------------------------------------------------------
Effective immediately, changes to the reminder-call policy:
- Section 4(c): customers 21–60 days in arrears get the 6th business day (not the 5th).
- Section 4(e): attempt one now proposes the full amount on the last business day of the current week
  (if the call is on that day, the last business day of the following week).
- Callbacks (section 2): the window ends at 18:00, not 17:30.
- 2026-12-31 is no longer a bank holiday.
Everything else stays as it is.
