# Workflow format

This page describes the workflow JSON that defines a Freya agent. Read it before you write a builder. Tools, API calls and code are in [tools-and-code.md](tools-and-code.md). The REST calls are in [api.md](api.md).

Some statements are marked "verified in a working builder". Those come from a builder that created a 6-node workflow through the REST API and whose agent passed its practice cases.

## What a workflow is

A workflow describes a conversation as a graph. Each **node** is one step of the conversation and has its own prompt. **Transitions** move the conversation from one node to the next. A transition fires on what the user said or on the value of a variable.

When you create a workflow through the API, the platform creates an agent for it. You run simulations against that agent.

## Three model calls per turn

After each user message the platform makes three separate model calls. They do not share a prompt.

```text
user message
    |
    v
1. EXTRACTION   reads the message, stores variables
2. ROUTING      decides whether to leave the node
3. DIALOGUE     writes the agent's reply
```

| Call | What it sees | What it produces |
|---|---|---|
| Extraction | Recent conversation messages and the current node's `extraction_schema` | Variable values |
| Routing | Recent conversation messages and the transition descriptions. It does not see the dialogue prompt | The transition to take, or none |
| Dialogue | `system_prompt`, `role_message`, `task_message`, the full conversation history, and the node's `tools` | The reply, or a tool call |

Consequences:

- A routing instruction inside `task_message` has no effect on routing. Routing reads only transitions.
- The dialogue model can call only the tools in the current node's `tools` array. Everything else (API calls on entry, code, ending the call) is run by the workflow engine.
- Deterministic conditions (variable checks) need no model call. They are evaluated in code.

## Top-level keys

```json
{
  "initial_node": "greeting",
  "system_prompt": "You are the assistant of a dental clinic. Speak English.",
  "nodes": {},
  "global_nodes": {},
  "test_variables": { "customer_id": "c_test" }
}
```

| Key | Type | Required | Meaning |
|---|---|---|---|
| `initial_node` | string | yes | Key of the node where every call starts |
| `nodes` | object | yes | Map of node key to node definition |
| `system_prompt` | string | no | Global rules. Part of the dialogue prompt in every node |
| `global_nodes` | object | no | Interrupt handlers that can fire from any node. See "Global nodes" |
| `test_variables` | object | no | Default values for call variables. See "Variables" |
| `context_variables` | object | no | A state block of chosen variables for the dialogue model. See "Context variables" |
| `tools` | array | no | Workflow-level lifecycle tools. See tools-and-code.md |
| `agent_config` | object | no | Model and call settings. See below |
| `nodePositions` | object | no | Layout for the visual editor. The working builder omits it |

**`agent_config`**: omit it. The platform fills in defaults. It holds model, voice and timeout settings that a builder for this event does not need. In a simulation you choose the models with the override fields described in api.md.

**No `null` values.** The schema is strict. Leave an optional field out, or set an optional string to `""`. A `null` fails validation.

The REST API takes the workflow inside a request body `{"name": "...", "workflow": {...}}`. The object described on this page is the value of `workflow`.

## Node types

| `node_type` | Purpose | Speaks to the user | Carries |
|---|---|---|---|
| `conversation` | A dialogue step | yes | `task_message`, `tools`, `extraction_schema`, `transitions` |
| `api_request` | Runs an HTTP call on entry | usually not | `pre_actions`, node-level `response_mapping`, `transitions` |
| `code` | Runs a Python snippet on entry | usually not | `pre_actions` with a `code_exec` function, `transitions` |
| `end_call` | Ends the call | optional farewell | `terminal` |

Other node types exist: `transfer_call`, `integration`, `knowledge_base`, `reschedule_call`, `invoke_agent`, `exit`. Telephony, voice settings, knowledge base and integrations also exist on the platform. You do not need any of them here and this page does not describe them.

The platform strips fields that do not belong to a node type, without an error:

- `tools` is kept only on `conversation` nodes.
- `pre_actions` is kept only on `api_request` and `code` nodes (and the other non-conversation action types).

So a node cannot have both. If a call must run before a conversation node, put it in its own `api_request` node in front.

## Node fields

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | | Node name. Use the same value as the node's key, in `snake_case` |
| `node_type` | string | | One of the types above |
| `task_message` | string | | The instruction for the dialogue model in this node |
| `role_message` | string | | Extra persona text for this node. Rarely needed |
| `on_enter` | object | `{"type": "llm"}` | What happens on entry. See "Entry behaviour" |
| `on_enter_first_entry_only` | boolean | `false` | Run the entry behaviour only on the first visit |
| `transitions` | array | | Outgoing transitions, in priority order |
| `routing_prompt` | string | | Extra context for the routing model in this node |
| `loop_condition` | string | | Intent description for staying in the node. See "Loop conditions" |
| `loop_prompt` | string | | Replaces `task_message` from the second turn in the node |
| `extraction_schema` | array | | Variables to extract from user speech in this node |
| `tools` | array | | Tools the dialogue model may call. `conversation` nodes only |
| `pre_actions` | array | | Calls the engine runs on entry. `api_request` and `code` nodes |
| `response_mapping` | array | | For `pre_actions` nodes: maps the call result to variables. Node level |
| `passthrough` | boolean | `false` | Route right after entry, without waiting for the user |
| `passthrough_default_transition` | string | | Target node for a passthrough node |
| `max_node_turns` | integer | `10` | Cap on user turns spent in the node |
| `max_turn_transition` | string | | Target node when the cap is reached |
| `terminal` | object | | The end-call function. `end_call` nodes only |
| `disable_inactivity_monitor` | boolean | `false` | Switch off silence check-ins for this node |
| `suppress_tool_results` | boolean | `false` | Hide raw call results from the dialogue model. See tools-and-code.md |
| `truncation_strategy` | string | `keep_all` | How much history the dialogue model sees. See "Limits" |
| `truncation_window_size` | integer | `10` | Number of recent messages kept by `keep_recent` and `summarize` |
| `reasoning_override` | string | `auto` | `enabled` or `disabled` forces model reasoning on or off for this node. Only models that support such a switch react to it |

A per-node `idle_config` (silence timeouts) and per-node speech settings also exist. They matter on voice calls only.

## Prompts

The dialogue model receives one system message built from three parts:

```text
system_prompt        workflow level, the same in every node
role_message         node level, optional
## Current Task
task_message         node level, what to do now
```

| Field | Level | Use it for |
|---|---|---|
| `system_prompt` | workflow | Identity, language, tone, rules that hold in every node |
| `role_message` | node | A different persona for one node. Most workflows leave it out |
| `task_message` | node | What the agent must do in this step |
| `loop_prompt` | node | A replacement for `task_message` after the first turn in the node |
| `on_enter` | node | What the agent does when it enters the node |

Rules for `task_message`:

- Write instructions for the model, not a script.
- Cover this node's job only.
- Do not describe routing or name other nodes. The model does not know about nodes. Text such as "then move to the lookup node" makes it narrate steps that have not happened.
- If the node has tools, refer to them by name and say when to call them. Do not repeat the tool descriptions.
- In a node without tools, state that no tool call is allowed in this turn. If the node has a `loop_prompt`, put that rule in both prompts.

Example:

```json
{
  "name": "collect_details",
  "node_type": "conversation",
  "task_message": "Ask which service the caller wants and on which day. Ask one question at a time. If the caller is unsure about the day, offer to check the next free days.",
  "transitions": []
}
```

### Entry behaviour

| `on_enter` | Behaviour |
|---|---|
| `{"type": "llm"}` | The model writes the first line from `task_message`. Default. An optional `prompt` key overrides the entry instruction for this node |
| `{"type": "tts", "text": "..."}` | A fixed line is spoken. No model call. `{{var}}` works in `text` |
| `{"type": "silent"}` | Nothing is said. The node waits for the user, or routes at once if it is a passthrough node |
| `{"type": "audio", "asset_id": "..."}` | Plays a recorded asset. Not needed here |

Set `on_enter_first_entry_only` to `true` when a node can be re-entered and must not repeat its opening line. This works better than a prompt rule such as "do not greet twice".

### History across nodes

When the conversation moves from node A to node B:

- User and assistant messages are kept.
- The system message is replaced by node B's prompts.
- A loop prompt from node A is removed.

So node B can refer to anything said earlier. Variables also stay for the whole call.

## Variables

All variables live in one table for the whole call. There is no per-node scope. A variable is never cleared on a transition. A later write with the same name overwrites it.

| Source | How it gets in |
|---|---|
| Call variables | Passed when the call or simulation starts |
| `test_variables` | Workflow-level defaults for call variables |
| Extraction | `extraction_schema` on a node |
| Call results | `response_mapping`, and the automatic result keys described in tools-and-code.md |
| Code | A code node or `code_exec` tool writes into `vars` |
| System | Set by the platform |

### `{{var}}` substitution

Write `{{variable_name}}` in prompts, `on_enter.text`, transition descriptions, URLs, headers and request bodies. The engine replaces it before the model or the HTTP call sees the text.

| Form | Result |
|---|---|
| `{{customer_name}}` | The value as a string |
| `{{amount:json}}` | The value JSON-encoded. Use it inside request bodies |

Behaviour to know:

- Date values are formatted for speech in the agent's language when they are substituted into a prompt.
- An unresolved variable in a prompt stays as the literal text `{{variable_name}}`. The model sees the placeholder. In a fixed spoken line (`on_enter.text`, a terminal `spoken_message`) the agent says it aloud.
- In a field of an engine-run call (a `pre_actions` call or a lifecycle tool) an unresolved placeholder behaves in two ways. If the value is exactly one placeholder (`"{{x}}"`), the whole field is dropped from the request. If the value mixes text and a placeholder (`"Status: {{x}}"`), the request goes out with the literal `{{x}}` in it.
- Do not reference a variable in a mixed value unless an earlier node always sets it.

### Call variables and `test_variables`

Call variables are the inputs of one call, for example a customer id or the current time. In a simulation you pass them per persona in `customerVariablesMap` (see api.md).

`test_variables` is a top-level object of default values. On a web call to the workflow it is merged into the call variables. A value passed with the call wins over a test variable of the same name.

```json
{
  "test_variables": {
    "customer_id": "c_test",
    "first_name": "Dana",
    "now": "2026-03-11T10:00"
  }
}
```

Verified in a working builder: call variables are readable as `{{customer_id}}` in prompts and tool parameters, and as `vars.get("customer_id")` in code.

### System variables

| Variable | Example | Meaning |
|---|---|---|
| `{{system.iso_utc_now}}` | `2026-03-11T14:30:00Z` | UTC timestamp of call start |
| `{{system.todays_date_en_cst}}` | `11 March 2026 Wednesday 08:30` | English date, UTC-6 |
| `{{system.todays_date_en_est}}` | `11 March 2026 Wednesday 09:30` | English date, UTC-5 |
| `{{system.todays_date_tr}}` | | Turkish date with day name and time, UTC+3 |
| `{{system.todays_date_tr.iso_8601}}` | `2026-03-11` | ISO date, UTC+3 |
| `{{system.conversation}}` | `AGENT: hello\nUSER: hi` | Transcript so far |
| `{{system.conversation.last-N}}` | | Last N turns. N is `1`, `5`, `10` or `20` |
| `{{call.direction}}` | `web` | `inbound`, `outbound`, `web` or `simulation`. A chat simulation in the trial showed `web` |
| `{{call.duration}}` | `42` | Whole seconds since call start |
| `{{call.call_id}}` | | Platform call id |
| `{{<node>.current_turns}}` | `2` | User turns in the node since the last entry. Resets on every transition |
| `{{<node>.total_turns}}` | `5` | User turns in the node over the whole call |

There is no `{{current_date}}` placeholder. These system dates are the real clock. If your task supplies its own "now" as a call variable, use that variable.

`{{system.conversation.last-N}}` is useful in a transition description or a `routing_prompt` when the routing model needs more than the last message.

### Context variables

Warning from a test on 10 October: a workflow saved over the API came back without this key, and the save gave no error. Do not rely on it. Write the values the model needs into the prompt with `{{variable}}` instead.

`context_variables` is a top-level key. It shows chosen variables to the dialogue model as a state block, so you do not have to write variable tables into prompt text.

```json
{
  "context_variables": {
    "pre_history_description": "Static call context",
    "post_history_description": "Live state",
    "items": [
      { "name": "customer_tier", "placement": "pre_history", "description": "Customer tier" },
      { "name": "attempt_count", "placement": "post_history" }
    ]
  }
}
```

| Field | Meaning |
|---|---|
| `items[].name` | Name of a variable in the variable table. Must match `^[a-zA-Z_]\w*$` and be unique across both placements |
| `items[].placement` | `pre_history` or `post_history` |
| `items[].description` | Optional label |
| `pre_history_description`, `post_history_description` | Heading text of each section |

Rules:

- An item points at a variable. It does not create one. If nothing sets the variable, the row is skipped without an error.
- `pre_history` is written once into the system prompt. Use it only for values that never change during the call.
- `post_history` is rendered again on every turn after the chat history and is not stored in the history. Use it for values that change.
- The block is rendered as `<CONTEXT_VARIABLES>`, one line `- name (description): value` per populated item.
- No other keys are allowed on an item. There is no `value`, `type` or `default`.
- It does not affect extraction or tool parameter substitution.

## Transitions

A transition is an object in a node's `transitions` array.

| Field | Type | Meaning |
|---|---|---|
| `target_node` | string | Key of the next node. May be the node itself. `__previous__` is allowed in global nodes |
| `description` | string | What the transition is for. The routing model reads it |
| `condition` | object | When the transition fires |
| `is_tool_call` | boolean | The dialogue model triggers the transition by calling a tool. See "Tool-call transitions" |

### Condition operators

Deterministic operators check a variable in code. No model call.

| Operator | Needs | True when |
|---|---|---|
| `equals` | `variable`, `operand` | `str(value) == str(operand)` |
| `not_equals` | `variable`, `operand` | The inverse of `equals` |
| `greater_than` | `variable`, `operand` | `float(value) > float(operand)` |
| `less_than` | `variable`, `operand` | `float(value) < float(operand)` |
| `contains` | `variable`, `operand` | `operand` is a substring of the value, ignoring case |
| `is_set` | `variable` | The variable has any value |
| `is_not_set` | `variable` | The variable has no value |
| `always` | nothing | Always |

The semantic operator uses the routing model.

| Operator | Needs | True when |
|---|---|---|
| `matches_intent` | `description` | The routing model judges that the user's last message matches the description |

All `matches_intent` conditions of one evaluation are judged in a single model call.

### Condition shapes

An unconditional transition:

```json
{ "target_node": "next_step", "description": "always", "condition": { "operator": "always" } }
```

An intent condition:

```json
{
  "target_node": "complaint",
  "description": "The user wants to complain",
  "condition": { "operator": "matches_intent", "description": "The user is unhappy or wants to file a complaint" }
}
```

Variable conditions go inside a group. The top-level group always uses `"logic": "or"`:

```json
{
  "target_node": "order_found",
  "description": "The lookup returned an order",
  "condition": {
    "logic": "or",
    "conditions": [
      { "variable": "order_status", "operator": "equals", "operand": "shipped" },
      { "variable": "order_status", "operator": "equals", "operand": "delivered" }
    ]
  }
}
```

For AND, nest a group inside the top-level OR. Never put `"logic": "and"` at the top level.

```json
{
  "target_node": "priority_desk",
  "description": "Gold customer with a late order",
  "condition": {
    "logic": "or",
    "conditions": [
      {
        "logic": "and",
        "conditions": [
          { "variable": "customer_tier", "operator": "equals", "operand": "gold" },
          { "variable": "days_late", "operator": "greater_than", "operand": 3 }
        ]
      }
    ]
  }
}
```

The working builder uses the bare form for `always` and the grouped form for every variable check. The internal reference also shows a bare single variable condition (`{"variable": ..., "operator": ..., "operand": ...}`) directly under `condition`.

### Do not route on a boolean

`equals` compares strings. A boolean can arrive as `"True"` or as `"true"`, depending on how it was written into the table. A mismatch fails silently: the branch never fires and nothing reports an error.

- Prefer a string value such as `verified` or `rejected`, written by your code or by the API.
- If you must test a boolean that comes from an API response, test both spellings. Verified in a working builder:

```json
{
  "target_node": "wrap_up",
  "description": "The booking call succeeded",
  "condition": {
    "logic": "or",
    "conditions": [
      { "variable": "booking_ok", "operator": "equals", "operand": "true" },
      { "variable": "booking_ok", "operator": "equals", "operand": "True" }
    ]
  }
}
```

`greater_than` and `less_than` convert both sides to numbers, so `2` and `"2"` behave the same. Use them for counters.

### Order of evaluation

After each user message, routing runs in this order. The first match wins and routing stops.

```text
1. loop_condition of the current node    match: stay in the node, use loop_prompt
2. the node's transitions, in list order match: go to target_node
3. global nodes                          match: enter the global node
4. nothing matched                       stay in the node, wait for the next user message
```

Within step 2:

- Transitions are checked in list order. Put specific conditions first and broad ones last.
- Deterministic conditions are evaluated first. If one matches, no routing model call is made.
- If several transitions of a node have the same `target_node`, the engine merges them at load time into one transition. Its condition is the OR of the originals. If one of them is unconditional, the merged transition is unconditional.

Routing also runs after a tool result arrives. Verified in a working builder: a transition on a variable that a tool's `response_mapping` sets fires in the same turn, without a further user message.

When nothing matches, there is no fallback. The agent stays and answers from the same `task_message`. Make sure every realistic path has a matching transition.

### `routing_prompt`

A node-level string. It replaces the default intent-matching instruction of the routing model for this node. Use it when the transition descriptions cannot carry the rule, for example "stay here until both the name and the date are given".

### Self-transition

A last transition with `always` that targets the node itself keeps the user in the node until an earlier transition matches.

```json
{ "target_node": "collect_details", "description": "Keep collecting", "condition": { "operator": "always" } }
```

Prefer this to `loop_condition` in most cases. All routing then lives in one ordered list.

### Loop conditions

`loop_condition` is an intent description. The routing model checks it before all transitions. When it matches, the agent stays in the node.

`loop_prompt` replaces `task_message` in the system message from the second turn in the node. The model sees one of the two, never both. Write it so that it stands alone. `{{var}}` works in it, so it can show what was already collected.

```json
{
  "name": "collect_contact",
  "node_type": "conversation",
  "task_message": "Ask for the caller's full name and email address.",
  "loop_condition": "The user has not yet given both a full name and an email address",
  "loop_prompt": "Name so far: {{customer_name}}. Email so far: {{email}}. Ask only for what is still missing. When both are present, read them back once.",
  "transitions": []
}
```

Make the loop condition specific. "The user has not finished" matches everything and the agent never leaves.

### Tool-call transitions

Set `is_tool_call` to `true` on a transition. The dialogue model then sees the transition as a tool named `transition_to_<node>` and triggers it by calling that tool. The router does not evaluate it after each turn.

```json
{
  "target_node": "confirm_booking",
  "description": "The caller accepted the offered slot",
  "is_tool_call": true,
  "condition": { "operator": "matches_intent", "description": "The caller accepted the offered slot" }
}
```

Use it when the agent should decide to move, for example because of something it just said or computed. The agent can acknowledge and move in the same message. The target node's `on_enter` then asks the next question. Global nodes accept the same flag.

### Passthrough nodes

A node with `"passthrough": true` routes right after its entry actions. It does not wait for the user. `api_request` and `code` nodes are normally passthrough nodes.

- Set `passthrough_default_transition` to the next node.
- End `transitions` with an `always` transition. A passthrough node with no matching transition deadlocks.
- Set `on_enter` to `{"type": "silent"}`, or to a short fixed line that covers the wait.

```json
{
  "name": "prepare",
  "node_type": "code",
  "passthrough": true,
  "passthrough_default_transition": "greeting",
  "on_enter": { "type": "silent" },
  "pre_actions": [],
  "transitions": [
    { "target_node": "greeting", "description": "always", "condition": { "operator": "always" } }
  ]
}
```

Verified in a working builder: a passthrough `code` node can be the `initial_node`. It runs before the agent says anything.

### Global nodes

A global node is an interrupt handler. It can fire from any node. It is checked only after the current node's own transitions found no match.

A global node has the same fields as a normal node, plus:

| Field | Meaning |
|---|---|
| `condition` | When the global node activates. Same format as a transition condition |
| `description` | Purpose of the node |
| `excluded_nodes` | Array of node keys where it must not fire |
| `is_tool_call` | Offer the global node to the dialogue model as a tool, not as a per-turn check |

`__previous__` as a `target_node` or as `passthrough_default_transition` returns to the node that was interrupted.

```json
{
  "global_nodes": {
    "off_topic": {
      "name": "off_topic",
      "description": "Brings the caller back to the subject",
      "condition": { "operator": "matches_intent", "description": "The user talks about something unrelated to their order" },
      "task_message": "Redirect the caller to the subject.",
      "on_enter": { "type": "tts", "text": "I can only help with your order. Let us continue." },
      "passthrough": true,
      "passthrough_default_transition": "__previous__",
      "excluded_nodes": ["goodbye"],
      "transitions": [
        { "target_node": "__previous__", "description": "always", "condition": { "operator": "always" } }
      ]
    }
  }
}
```

Rules:

- List terminal nodes in `excluded_nodes`, or the global node can loop.
- Exclude nodes where an interrupt would do harm, for example an identity check.
- For a plain redirect use a passthrough node with a fixed line. It is faster and more predictable than a model reply.
- Use global nodes for interrupts that can happen anywhere. Do not copy the same transition into every node.

## Extraction schema

`extraction_schema` is an array on a node. After each user message the extraction model fills the listed variables from the conversation.

```json
{
  "extraction_schema": [
    {
      "name": "order_number",
      "type": "string",
      "description": "The order number the caller reads out",
      "validation_pattern": "^[0-9]{8}$",
      "max_retries": 2,
      "min_confidence": 0.8
    },
    {
      "name": "request_type",
      "type": "string",
      "enum_values": ["status", "cancel", "change_address", "other"],
      "description": "What the caller wants to do with the order",
      "min_confidence": 0.7
    }
  ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Variable name |
| `type` | string | `string`, `integer`, `float`, `boolean`, `date`, `datetime`, `name`, `phone_number` |
| `description` | string | What the variable is |
| `enum_values` | array | Allowed values. Works on every type. The old `enum` type is deprecated and becomes `string` |
| `extraction_prompt` | string | A custom extraction template. See the warning below |
| `validation_pattern` | string | Regular expression the value must match |
| `min_confidence` | number | 0.0 to 1.0. Values below it are discarded. Default `0.95` |
| `max_retries` | integer | Retries after a failed validation, with the error given to the model |

How it works:

1. The extraction model sees recent messages and the schema.
2. It returns structured values.
3. Confidence is computed from the model's token probabilities, not from a self-report.
4. Each value is checked against `validation_pattern` and `enum_values`.
5. On failure the model retries, up to `max_retries`.

Rules:

- **Set `min_confidence` on every variable.** The default of 0.95 is strict. A discarded value leaves no trace in the transcript, so it looks the same as "nothing was extracted".
- **`extraction_prompt` replaces the whole built-in template.** It is not appended. A custom prompt must contain the input placeholders itself: `{{extractor.speech}}`, `{{extractor.conversation.last-10}}`, `{{extractor.type_preamble}}` and `{{extractor.variables_list}}`. Without them the extractor never sees the user's message and returns nothing on every turn, while dialogue and routing look healthy.
- **Declare dates as `type: "date"`.** The date types give the extractor today's date and the rules for relative dates such as "tomorrow". A date typed as `string` gets no date anchor and the model guesses the year.
- The built-in date rules turn vague expressions such as "next week" into a concrete date. If you need vague dates rejected, a custom prompt must say so and state that this overrides the general rules.
- No `null`. Omit optional fields or use `""`.
- An extracted variable is available to the same node's transitions in the same turn, and to every later node.

Inside `extraction_prompt` these date placeholders resolve: `{{date.today}}`, `{{time.now}}`, `{{date.day_of_week}}`, `{{date.yesterday}}`, `{{date.tomorrow}}`, `{{date.day_after_tomorrow}}`, `{{date.next_week}}`, `{{date.end_of_month}}`, `{{date.first_next_month}}`, `{{date.next_mon}}` to `{{date.next_sun}}`, `{{date.last_mon}}` to `{{date.last_sun}}`, `{{date.fnm_mon}}` to `{{date.fnm_sun}}` (first such weekday of next month), `{{date.weeks2}}`, `{{date.weeks3}}`, `{{date.weeks2_ago}}`, `{{date.weeks3_ago}}`. Do not rely on them outside extraction prompts.

**Fork on an extracted enum.** To route from one node to several paths, extract an enum and branch with `equals`. This is more reliable than several competing `matches_intent` transitions.

```json
{
  "name": "menu",
  "node_type": "conversation",
  "task_message": "Tell the caller the order status in one sentence. Then ask whether they want to change the delivery address, cancel the order, or end the call.",
  "extraction_schema": [
    {
      "name": "next_action",
      "type": "string",
      "enum_values": ["change_address", "cancel", "done"],
      "description": "What the caller chose. Empty if unclear.",
      "min_confidence": 0.7
    }
  ],
  "transitions": [
    { "target_node": "change_address", "description": "Change address", "condition": { "logic": "or", "conditions": [ { "variable": "next_action", "operator": "equals", "operand": "change_address" } ] } },
    { "target_node": "cancel_order", "description": "Cancel", "condition": { "logic": "or", "conditions": [ { "variable": "next_action", "operator": "equals", "operand": "cancel" } ] } },
    { "target_node": "goodbye", "description": "Done", "condition": { "logic": "or", "conditions": [ { "variable": "next_action", "operator": "equals", "operand": "done" } ] } },
    { "target_node": "menu", "description": "Unclear, stay", "condition": { "operator": "always" } }
  ]
}
```

Use extraction for user speech. For API responses use `response_mapping` (tools-and-code.md). It is deterministic and needs no model call.

## End-call nodes

An `end_call` node hangs up. It has a `terminal` object and no outgoing transitions.

```json
{
  "name": "goodbye",
  "node_type": "end_call",
  "on_enter": { "type": "silent" },
  "disable_inactivity_monitor": true,
  "transitions": [],
  "terminal": {
    "type": "function",
    "function": {
      "name": "closing_end",
      "handler": "__function__:end_call",
      "parameters": {
        "type": "object",
        "properties": {
          "message_mode": { "type": "string", "default": "custom" },
          "spoken_message": { "type": "string", "default": "Thank you for calling. Goodbye." }
        }
      }
    }
  }
}
```

| Parameter | Meaning |
|---|---|
| `message_mode` | `custom`: say `spoken_message`. `llm`: the model writes the farewell from `llm_prompt`. `none`: hang up without a farewell |
| `spoken_message` | The fixed farewell for `custom`. `{{var}}` works |
| `llm_prompt` | The instruction for `llm` |
| `interruptible` | `true` opens a short window after the farewell in which the user can still speak. Default: hang up as soon as the agent stops speaking |
| `trigger_timeout` | Length of that window in seconds |
| `trigger_pattern_both` | Farewell phrases, separated by `\|`, that do not cancel the close. Anything else the user says in the window cancels the close and returns the turn to the agent |

Rules:

- **The farewell comes from the terminal, not from `on_enter`.** A node with an `on_enter` line and `message_mode: "none"` hangs up silently. Put the sentence in `spoken_message` and set `on_enter` to `{"type": "silent"}`.
- Set `disable_inactivity_monitor` to `true` and `transitions` to `[]`.
- **The call's `endedReason` is the terminal's `function.name`.** The node name does not affect it. Pick a name that describes the outcome.
- Use several end-call nodes with different farewells and function names when outcomes differ.
- If you set `interruptible`, also set `trigger_pattern_both`. Without a phrase list every polite reply cancels the hang-up. The window is timed on a wall clock and a chat simulation cannot measure it.

Verified in a working builder: `message_mode: "none"` with a silent `on_enter` ends the call when the node is reached. The agent says its goodbye in the previous conversation node.

## Limits

| Limit | Default | Notes |
|---|---|---|
| `max_node_turns` | `10` | Cap on user turns in one node. Only user messages count. Tool results and agent messages do not. There is no "unlimited" value |
| `max_turn_transition` | none | Where to go when the cap is reached. Without it the engine records the overrun and continues with normal routing, so the cap changes nothing |
| `truncation_strategy` | `keep_all` | `keep_all`: full history. `keep_recent`: system message plus the last `truncation_window_size` messages. `summarize`: older messages are replaced by a model-written summary |
| `truncation_window_size` | `10` | Used by `keep_recent` and `summarize` |
| Extraction `min_confidence` | `0.95` | See "Extraction schema" |
| Code `timeout_ms` | `30000` | See tools-and-code.md |

Notes:

- Truncation applies to the dialogue model only. Extraction and routing run before it.
- Give every node that sets `max_node_turns` a `max_turn_transition`. The working builder sets `max_node_turns` to 60 and 80 on its conversation nodes without a `max_turn_transition`. Its calls ended well below those counts, so the behaviour at the cap is not confirmed by it.
- Size the cap from real conversations. A node that handles a whole call can need dozens of user turns.
- The maximum call length in a simulation is set with `maxCallDurationSeconds` (api.md).

## Design rules

- Use `snake_case` node keys that describe the step.
- Keep dialogue in `task_message`, routing in `transitions`, data capture in `extraction_schema`.
- Every path must reach an `end_call` node.
- Put deterministic conditions before `matches_intent` conditions.
- Every passthrough node ends with an `always` transition.
- A transition back to an earlier node is supported.
- Split a step into its own node when it has strict rules of its own or forms a clear state. Keep related optional actions together in one conversation node with several tools.

## Complete example

A clinic assistant. It collects a service and a day, looks up free slots, lets the model book one with a tool, and ends the call.

```json
{
  "initial_node": "collect",
  "system_prompt": "You are the phone assistant of a dental clinic. Speak English. Keep every turn to one or two short sentences.",
  "test_variables": { "patient_id": "p_test", "first_name": "Dana" },
  "global_nodes": {},
  "nodes": {
    "collect": {
      "name": "collect",
      "node_type": "conversation",
      "on_enter": { "type": "tts", "text": "Hello {{first_name}}, this is the clinic. Which treatment would you like to book, and on which day?" },
      "on_enter_first_entry_only": true,
      "task_message": "Find out which treatment the caller wants (checkup, cleaning or filling) and on which day. Ask one question at a time. Do not call a tool in this turn.",
      "extraction_schema": [
        { "name": "treatment", "type": "string", "enum_values": ["checkup", "cleaning", "filling"], "description": "Treatment the caller wants", "min_confidence": 0.7 },
        { "name": "wanted_day", "type": "date", "description": "Day the caller wants the appointment", "min_confidence": 0.7 }
      ],
      "max_node_turns": 12,
      "max_turn_transition": "goodbye_no_booking",
      "transitions": [
        {
          "target_node": "find_slots",
          "description": "Treatment and day are known",
          "condition": {
            "logic": "or",
            "conditions": [
              {
                "logic": "and",
                "conditions": [
                  { "variable": "treatment", "operator": "is_set" },
                  { "variable": "wanted_day", "operator": "is_set" }
                ]
              }
            ]
          }
        },
        { "target_node": "collect", "description": "Keep collecting", "condition": { "operator": "always" } }
      ]
    },
    "find_slots": {
      "name": "find_slots",
      "node_type": "api_request",
      "passthrough": true,
      "passthrough_default_transition": "offer",
      "on_enter": { "type": "silent" },
      "disable_inactivity_monitor": true,
      "pre_actions": [
        {
          "type": "function",
          "config": { "timeoutMs": 10000, "maxRetries": 2 },
          "function": {
            "name": "find_slots",
            "handler": "__function__:api_call",
            "description": "Get free slots for a day.",
            "parameters": {
              "type": "object",
              "properties": {
                "url": { "type": "string", "default": "https://api.example.com/v1/slots" },
                "method": { "type": "string", "default": "POST" },
                "headers": { "type": "object", "properties": { "Content-Type": { "type": "string", "default": "application/json" } } },
                "body": {
                  "type": "object",
                  "properties": {
                    "treatment": { "type": "string", "default": "{{treatment}}" },
                    "day": { "type": "string", "default": "{{wanted_day}}" }
                  }
                }
              }
            }
          }
        }
      ],
      "response_mapping": [
        { "path": "data.slots_text", "variable": "slots_text" }
      ],
      "transitions": [
        { "target_node": "goodbye_no_booking", "description": "The lookup failed", "condition": { "logic": "or", "conditions": [ { "variable": "find_slots_failure_count", "operator": "greater_than", "operand": 0 } ] } },
        { "target_node": "offer", "description": "always", "condition": { "operator": "always" } }
      ]
    },
    "offer": {
      "name": "offer",
      "node_type": "conversation",
      "task_message": "Free slots: {{slots_text}}\n\nOffer the earliest slot. If the caller refuses it, offer the next one. When the caller accepts a slot, read back the treatment, the day and the time and wait for a clear yes. Then CALL book_appointment. Saying that it is booked is not enough. After the tool result, tell the caller whether the booking worked and say goodbye.",
      "tools": [
        {
          "type": "function",
          "config": { "timeoutMs": 10000, "maxRetries": 0 },
          "function": {
            "name": "book_appointment",
            "handler": "__function__:api_call",
            "description": "Book one slot. CALL it only after the caller confirmed the read-back.",
            "parameters": {
              "type": "object",
              "properties": {
                "url": { "type": "string", "default": "https://api.example.com/v1/bookings" },
                "method": { "type": "string", "default": "POST" },
                "headers": { "type": "object", "properties": { "Content-Type": { "type": "string", "default": "application/json" } } },
                "body": {
                  "type": "object",
                  "properties": {
                    "patient_id": { "type": "string", "default": "{{patient_id}}" },
                    "treatment": { "type": "string", "default": "{{treatment}}" },
                    "slot_time": { "type": "string", "description": "Start time of the accepted slot, HH:MM, 24 hour", "default": "{{slot_time}}" }
                  },
                  "required": ["slot_time"]
                }
              }
            }
          },
          "response_mapping": [
            { "path": "data.booking_id", "variable": "booking_id" }
          ]
        }
      ],
      "max_node_turns": 20,
      "max_turn_transition": "goodbye_no_booking",
      "transitions": [
        { "target_node": "goodbye_booked", "description": "The booking was recorded", "condition": { "logic": "or", "conditions": [ { "variable": "booking_id", "operator": "is_set" } ] } },
        { "target_node": "goodbye_no_booking", "description": "The caller does not want any slot", "condition": { "operator": "matches_intent", "description": "The caller refused all offered slots or does not want to book" } }
      ]
    },
    "goodbye_booked": {
      "name": "goodbye_booked",
      "node_type": "end_call",
      "on_enter": { "type": "silent" },
      "disable_inactivity_monitor": true,
      "transitions": [],
      "terminal": {
        "type": "function",
        "function": {
          "name": "booked",
          "handler": "__function__:end_call",
          "parameters": { "type": "object", "properties": { "message_mode": { "type": "string", "default": "none" } } }
        }
      }
    },
    "goodbye_no_booking": {
      "name": "goodbye_no_booking",
      "node_type": "end_call",
      "on_enter": { "type": "silent" },
      "disable_inactivity_monitor": true,
      "transitions": [],
      "terminal": {
        "type": "function",
        "function": {
          "name": "no_booking",
          "handler": "__function__:end_call",
          "parameters": {
            "type": "object",
            "properties": {
              "message_mode": { "type": "string", "default": "custom" },
              "spoken_message": { "type": "string", "default": "No appointment was booked. You can call us again at any time. Goodbye." }
            }
          }
        }
      }
    }
  }
}
```

What the example shows:

| Node | Feature |
|---|---|
| `collect` | Fixed opening line, extraction with a `date` type, AND group, self-transition, turn cap with a target |
| `find_slots` | Passthrough `api_request` node, baked parameters, node-level `response_mapping`, failure counter, `always` fallback |
| `offer` | A tool the model calls, a model-filled body field, tool-level `response_mapping`, routing on the mapped variable |
| `goodbye_booked`, `goodbye_no_booking` | Two end-call nodes with different `endedReason` values |
