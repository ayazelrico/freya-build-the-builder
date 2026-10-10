# Tools and code

This page describes how a workflow calls HTTP APIs and runs Python. Read [workflow-format.md](workflow-format.md) first.

Statements marked "verified in a working builder" come from a builder that created a 6-node workflow through the REST API. The workflow has code nodes, `api_call` tools, post-hooks and transitions on tool results. Its agent passed its practice cases. Statements marked "seen in a trial call" come from the event log of a simulation call made with that builder.

## Tool function shape

Every external action is a **tool function**. The shape is the same wherever you attach it.

```json
{
  "type": "function",
  "config": { "timeoutMs": 10000, "maxRetries": 2 },
  "function": {
    "name": "lookup_order",
    "handler": "__function__:api_call",
    "description": "Look up one order. CALL it when the caller asks about a specific order.",
    "parameters": {
      "type": "object",
      "properties": {
        "url": { "type": "string", "default": "https://api.example.com/v1/orders/lookup" },
        "method": { "type": "string", "default": "POST" },
        "headers": {
          "type": "object",
          "properties": { "Content-Type": { "type": "string", "default": "application/json" } }
        },
        "body": {
          "type": "object",
          "properties": {
            "customer_id": { "type": "string", "default": "{{customer_id}}" },
            "order_number": { "type": "string", "description": "Order number, digits only", "default": "{{order_number}}" }
          },
          "required": ["order_number"]
        }
      }
    }
  },
  "response_mapping": [
    { "path": "data.status", "variable": "order_status" }
  ]
}
```

| Field | Meaning |
|---|---|
| `type` | Always `"function"` |
| `function.name` | Tool name. The model calls it by this name. Result variables are named after it |
| `function.handler` | Which runtime executes the tool. See the table below |
| `function.description` | Read by the dialogue model when the tool is in `tools`. Ignored in `pre_actions` |
| `function.parameters` | JSON-schema object. `properties` holds the parameters |
| `config.timeoutMs` | Timeout of one attempt, in milliseconds |
| `config.maxRetries` | Tool-level retries of a failed call |
| `config.interruptible` | `false` makes the tool run in the background. See "Background tools" |
| `config.alwaysRunsAt` | Makes the tool a lifecycle tool. See "Lifecycle tools" |
| `response_mapping` | Tool level, for tools in `tools`. Maps the result to variables |
| `pre_process_code` | Python hook that runs before the call |
| `post_process_code` | Python hook that runs after the call |

| Handler | Runs |
|---|---|
| `__function__:api_call` | An HTTP request |
| `__function__:code_exec` | A Python snippet in a sandbox |
| `__function__:end_call` | Hangs up. Used in the `terminal` of an `end_call` node |

Handlers for integrations, knowledge search, call transfer and rescheduling also exist. They are not needed here.

`api_call` parameters:

| Parameter | Meaning |
|---|---|
| `url` | Request URL. `{{var}}` works |
| `method` | HTTP method |
| `headers` | Object. Each header is a property with a `default` |
| `body` | Object. Each body field is a property under `body.properties` |
| `connect_retries` | Transport retries. See "Retries and timeouts" |

## How a parameter gets its value

One key decides, per parameter: `default`.

| Declaration | Who supplies the value | Does the model see the parameter |
|---|---|---|
| `default` with a literal, or with a `{{var}}` that has a value | The workflow. The value is **baked** | No |
| `default` with a `{{var}}` that has no value when the node is entered | The model | Yes, named after the variable, with the property's `type`, `description` and `enum` |
| no `default` | The model | Yes |
| `const` | Nobody. `const` does **not** bake | It only constrains the model's own output |

Rules:

- **Use `default` for fixed backend config** such as `url`, `method` and auth headers. At registration the engine moves every `default` into the tool's base config, resolves `{{var}}` from the variable table, and removes the field from the schema the model sees.
- **Never use `const` for a value you want sent.** The engine reads only `default`. A `{{var}}` inside a `const` never resolves. An `api_call` whose `url` is a `const` fails with "URL is required".
- **Baking happens when the node is entered.** A `{{var}}` default is resolved against the variable table at that moment.

The working builder uses this for every tool: `customer_id` has `"default": "{{customer_id}}"` and is baked from a call variable. Every other body field has `"default": "{{<field name>}}"`, where no variable of that name exists, so the model fills it. Verified in a working builder.

Seen in a trial call: the model's arguments are stored as `<tool>_args.<field>` in the variable table, for example `lookup_order_args.order_number`. They were not stored under the bare field name.

Take care that a model-filled field does not share its name with a variable that is already set when the node is entered. The value would be baked and the model would never see the parameter.

### `api_call` body field rules

- Declare each body field as a leaf under `body.properties.<field>`.
- Put the field's `type`, `description` and `enum` on that leaf. Put required fields in `body.required`.
- Give each leaf its own `default`.
- Do not put a field spec at the top level of `parameters.properties` next to a `body.default` template object. The engine looks for the spec at `body.properties.<field>`, does not find it, and the model sees only "Template variable: name". The `enum` and `description` are lost while the call still works.
- A body that exists only as one `body.default` object also shows as an empty form in the dashboard editor. Saving from there removes the tool.

A `code_exec` tool is different: its parameters are true top-level arguments. Declare a model-filled one as a top-level property without `default`.

### When a baked variable has no value

| Field type | Variable unset | Variable is `""` |
|---|---|---|
| Normal field in an engine-run call (`pre_actions`, lifecycle tool) | The field is dropped from the request. No error | The field is sent empty |
| `code` of `code_exec` | The literal text `{{var}}` stays in the Python source and the snippet crashes | |

Fix: make sure an earlier node always sets the variable, even to a sentinel value. In code, read variables from `vars` and do not splice them in with `{{var}}`.

### Constrain model-filled parameters

When a value must be one of a known set, do not use a free string. The model sometimes invents a value that looks plausible.

- Use an `enum` on the leaf, and list the values in the `description` as well.
- Or use a `number` that is an index into a list, with the valid range in the description. A pre-hook or the backend turns the index into the real value.
- If neither is possible, name the exact source in the description and tell the model to copy the value unchanged.

```json
{
  "type": "object",
  "properties": {
    "queue": {
      "type": "string",
      "description": "Team that takes over. One of: billing, delivery, returns.",
      "enum": ["billing", "delivery", "returns"],
      "default": "{{queue}}"
    }
  },
  "required": ["queue"]
}
```

## `pre_actions` versus `tools`

The placement decides who fires the call.

| Placement | Node type | Who calls it | When |
|---|---|---|---|
| `pre_actions` | `api_request`, `code` | The engine | On node entry, before any model turn |
| `tools` | `conversation` | The dialogue model | During a turn, when the model decides to |
| Workflow-level `tools` with `config.alwaysRunsAt` | none | The engine | At call start or call end |

The platform removes `tools` from non-conversation nodes and `pre_actions` from conversation nodes. It does so without an error: the JSON you sent looks fine, the create call succeeds, and the stored node has an empty array. A node cannot use both.

**Use `pre_actions`** when the call must always run and the model has nothing to decide. Example: after the order number is known, always fetch the order.

**Use `tools`** when the call depends on what the user says. Example: cancel the order only if the caller asks for it.

Differences in behaviour:

| | `pre_actions` | `tools` |
|---|---|---|
| Can be skipped | No | Yes. The model may not call it if the description and the prompt do not push for it |
| Timing | Node entry | Inside a turn. The model can call a tool, speak, then call another |
| Result in the conversation | A tool call and tool result pair is added to the history | The same |
| `response_mapping` lives | On the **node** | On the **tool** |
| `description` | Ignored | The only text the model reads about the tool |

To run a fixed call before a tool-driven conversation, use a passthrough `api_request` node and transition from it into the conversation node. Do not build a long chain of passthrough nodes for optional actions. Put those into one conversation node with several tools.

### A `pre_actions` node

```json
{
  "name": "fetch_order",
  "node_type": "api_request",
  "passthrough": true,
  "passthrough_default_transition": "present",
  "on_enter": { "type": "silent" },
  "pre_actions": [
    {
      "type": "function",
      "config": { "timeoutMs": 10000, "maxRetries": 2 },
      "function": {
        "name": "get_order",
        "handler": "__function__:api_call",
        "description": "Get the order.",
        "parameters": {
          "type": "object",
          "properties": {
            "url": { "type": "string", "default": "https://api.example.com/v1/get_order" },
            "method": { "type": "string", "default": "POST" },
            "headers": { "type": "object", "properties": { "Content-Type": { "type": "string", "default": "application/json" } } },
            "body": { "type": "object", "properties": { "order_number": { "type": "string", "default": "{{order_number}}" } }, "required": [] }
          }
        }
      }
    }
  ],
  "response_mapping": [
    { "path": "data.items", "variable": "items" }
  ],
  "transitions": [
    { "target_node": "present", "description": "always", "condition": { "operator": "always" } }
  ]
}
```

The last `always` transition is mandatory. A passthrough node with no matching transition deadlocks.

### Tool descriptions

In `tools`, the `description` decides whether the model calls the tool.

- Write it as an instruction with the trigger: "CALL it every time the caller gives an order number."
- A plain description such as "Looks up an order" lets the model acknowledge the request in words and never call the tool. That is the most common failure of nodes with many tools.
- If two tools could match, say which one not to use and name the other.
- In `task_message`, put the tool rules before long reference text and state: when a rule says to use a tool, call the tool.
- The working builder also tells the model to call one tool per message and to speak after every tool result. Verified in a working builder. In a trial call a model turn with no text and no tool call produced the error event "The model returned no speakable content".

A tool is available only in the nodes that list it. Seen in a trial call: the model called a tool that the current node did not list. The result was the text "The function `<name>` is not currently available."

## `response_mapping`

`response_mapping` copies values from a call result into named variables. It needs no model call.

```json
{
  "response_mapping": [
    { "path": "data.status", "variable": "order_status" },
    { "path": "data.items", "variable": "items" }
  ]
}
```

| Field | Meaning |
|---|---|
| `path` | Dot path into the tool result |
| `variable` | Name of the variable to set |

### Placement

- For a tool in `tools`: inside the tool object, next to `function` and `config`.
- For `pre_actions`: at the **node level**. A `response_mapping` nested inside a `pre_actions` entry is ignored and the variable never appears.

`extraction_schema` follows the same placement rule if you use it on a call result.

### Where a result lands (trial findings)

Seen in a trial call: the result of an `api_call` is an envelope around the HTTP response.

```json
{
  "status": "success",
  "data": { "ok": true, "verified": true, "attempts_left": 3 },
  "message": "Successfully executed POST request",
  "status_code": 200,
  "header": { "Content-Type": "application/json" }
}
```

`data` is the JSON body the API returned. `header` holds the HTTP response headers.

The engine also writes every result into the variable table by itself, flattened with dots. You do not need a mapping for these. For a tool named `check_answer` whose API returned `{"ok": true, "verified": true, "attempts_left": 3}`, the trial call's variable table held:

| Variable | Value |
|---|---|
| `check_answer_args.<field>` | Each argument the model sent |
| `check_answer_response.status` | `success` |
| `check_answer_response.data.ok` | `true` (a string) |
| `check_answer_response.data.verified` | `true` (a string) |
| `check_answer_response.data.attempts_left` | `3` |
| `check_answer_response.message` | `Successfully executed POST request` |
| `check_answer_response.status_code` | `200` |
| `check_answer_response.header.<Header-Name>` | One variable per response header |
| `check_answer_status_code` | `200` |
| `check_answer_success_count` | Number of successful calls so far |

Each call of the same tool overwrites the previous `_args` and `_response` values.

### Which mapping paths work

- **Start the path at the envelope, with `data.`**. If the API returns `{"ok": true}`, map `data.ok`. If it returns `{"products": [...]}`, map `data.products`. Verified in a working builder, on a tool-level mapping and on a node-level mapping.
- A path without the `data.` prefix (for the same body: `ok`) is not confirmed. A smaller example builder uses it. In an early trial call the mapped variables stayed unset and the transitions on them never fired. The mapping paths of that call are not recorded. The builder that passed uses `data.` paths.
- The flattened key can be used directly as a transition variable: `check_answer_response.data.verified`. Verified in a working builder, which tests the mapped variable and the flattened key in the same OR group as a safeguard.
- Booleans arrive as strings. The trial call showed `true` in lower case in the flattened keys. Test both `"true"` and `"True"`, or map a string field.
- A mapped list or object: the exact form it has later inside `vars` is not confirmed. The working builder reads it defensively. It accepts a list, a JSON string, and flattened keys.

## Routing on tool results

Routing runs again after a tool result arrives. A transition on a result variable fires in the same turn, before any further model turn. Seen in a trial call.

```json
{
  "transitions": [
    {
      "target_node": "load_order",
      "description": "The check passed",
      "condition": {
        "logic": "or",
        "conditions": [
          { "variable": "check_passed", "operator": "equals", "operand": "true" },
          { "variable": "check_passed", "operator": "equals", "operand": "True" },
          { "variable": "check_answer_response.data.verified", "operator": "equals", "operand": "true" },
          { "variable": "check_answer_response.data.verified", "operator": "equals", "operand": "True" }
        ]
      }
    }
  ]
}
```

Rules:

- On a passthrough node, end with an `always` transition so that a failed or empty response does not deadlock.
- Use a tool result to leave a conversation node. The pattern "a closing tool sets a variable, a transition on that variable leads to an `end_call` node" is verified in a working builder.
- To leave a node that carries out an action, do not re-test the user's earlier intent with `matches_intent`. The router looks at the latest user message and can route away before the tool was called. Extract a follow-up enum with a default such as `stay`, and branch with `equals`.

### Success and failure counters

The engine keeps two integer variables per call target. No mapping is needed.

| Placement | Variables |
|---|---|
| `pre_actions` node | `<nodeId>_success_count`, `<nodeId>_failure_count` |
| Tool in `tools` with handler `api_call` | `<toolName>_success_count`, `<toolName>_failure_count` |

Seen in a trial call: `check_answer_success_count` was `2` after two successful calls, and a code node named `setup` produced `setup_success_count` with the value `1`.

```json
{
  "transitions": [
    { "target_node": "give_up", "description": "The lookup failed three times", "condition": { "logic": "or", "conditions": [ { "variable": "lookup_order_failure_count", "operator": "greater_than", "operand": 2 } ] } },
    { "target_node": "ask_again", "description": "always", "condition": { "operator": "always" } }
  ]
}
```

### `suppress_tool_results`

A node-level boolean for nodes that run API calls. With `true` the dialogue model sees only a short `{status: "success"}` summary in place of the raw response. Variables are still mapped and routing still sees them. Use it for large responses, or when the mapped variables already hold everything the model needs.

### Background tools

A tool with `"config": {"interruptible": false}` runs in the background. A user interruption does not cancel it. Its result arrives one or more turns later. The mapped variables, the `_response` keys and the counters are filled as usual, but not in the same turn. A transition that reads them right after the call can find them unset. Gate on the variable with `is_set`.

## Retries and timeouts

| Setting | Where | Default | What it does |
|---|---|---|---|
| `timeoutMs` | `config` | not documented | Time limit of one attempt, in milliseconds |
| `maxRetries` | `config` | not documented | Tool-level retries after a failed response |
| `connect_retries` | `parameters.properties`, as a baked parameter | `2` | Retries when the connection could not be established |
| `timeout_ms` | `code_exec` parameter | `30000` | Time limit of a code snippet |

`connect_retries` in detail:

- It retries only failures to establish the connection: connection refused, or reset during the TCP or TLS handshake. The request never reached the server, so a repeat is safe even for POST.
- HTTP error statuses and timeouts are not retried by it.
- Hard cap `5`. `0` means a single attempt.
- Back-off is 150 ms times the attempt number, with a new connection each time.
- All attempts share one 30 second budget for the request.
- Declare it next to `url` and `method`: `"connect_retries": {"type": "number", "default": 0}`. It is not a `config` field.

The working builder sets `maxRetries` to `0` on tools that write data and to `2` on its read-only `pre_actions` call. A retried write can record the same thing twice if the API is not idempotent.

## Pre and post Python hooks

An `api_call` tool can carry two Python snippets. They run on the server, in a sandbox, right before and right after the call. They are top-level fields of the tool object.

```json
{
  "type": "function",
  "config": { "timeoutMs": 10000, "maxRetries": 0 },
  "function": {
    "name": "check_answer",
    "handler": "__function__:api_call",
    "description": "Check one answer. CALL it every time the caller answers the question.",
    "parameters": {
      "type": "object",
      "properties": {
        "url": { "type": "string", "default": "https://api.example.com/v1/check_answer" },
        "method": { "type": "string", "default": "POST" },
        "body": { "type": "object", "properties": { "answer": { "type": "string", "description": "The caller's answer", "default": "{{answer}}" } }, "required": ["answer"] }
      }
    }
  },
  "pre_process_code": "vars['member_code'] = str(vars.get('member_code') or '').strip().upper()",
  "post_process_code": "try:\n    if isinstance(result, dict):\n        result.pop('header', None)\n        d = result.get('data')\n        if isinstance(d, dict):\n            d['what_to_do_next'] = 'Ask the next question.' if d.get('verified') else 'Ask the same question again.'\nexcept Exception:\n    pass\n"
}
```

| Hook | Names available | Use |
|---|---|---|
| `pre_process_code` | `vars`: mutable dict that fills the `{{var}}` placeholders of the request. `config`: the substituted request with `url`, `method`, `headers`, `body` | Clean a value, or rewrite the whole request |
| `post_process_code` | `result`: the tool result, mutable | Reshape, shorten or extend the result |

Documented behaviour:

- The post-hook runs before `response_mapping` and extraction see the result.
- An empty or whitespace-only string means no hook.
- Hooks are honoured only on `api_call` tools (and on the integration and knowledge search handlers). The platform removes them from any other handler when the workflow is saved.
- In a pre-hook, setting `config['body']` to a string sends that string as the raw body, with no JSON encoding. Set the `Content-Type` header yourself in that case.

### What `result` looks like in a post-hook

The internal reference shows `result` as the response body. A working builder shows otherwise. Verified in a working builder:

- For an `api_call`, `result` is the envelope described above: a dict with `status`, `data`, `message`, `status_code` and `header`. The API's JSON body is `result["data"]`.
- A key that the hook adds inside `result["data"]` reaches the dialogue model as part of the tool result. The working builder adds a `what_to_do_next` sentence there, and its prompt tells the model to obey it.
- `result.pop("header", None)` removes the response headers. The working builder does this on every tool, so that headers do not take up space in the model's context.
- Mapping paths still start with `data.` when a post-hook is present.

The working builder writes every hook inside `try` and `except Exception: pass` and checks types with `isinstance` before use. What the platform does when a hook raises is not documented.

Seen in a test on 10 October: a post-hook can read call variables and write new variables, and a later pre-hook reads them. Not confirmed: whether a change to `result` also changes the flattened `<tool>_response.*` variables.

## Code nodes and `code_exec`

A `code` node runs a Python snippet when it is entered. The snippet is a `code_exec` function in `pre_actions`.

```json
{
  "name": "compute_delivery",
  "node_type": "code",
  "passthrough": true,
  "passthrough_default_transition": "tell_delivery",
  "on_enter": { "type": "silent" },
  "pre_actions": [
    {
      "type": "function",
      "function": {
        "name": "code_exec",
        "handler": "__function__:code_exec",
        "parameters": {
          "type": "object",
          "properties": {
            "code": { "type": "string", "default": "import datetime\ntry:\n    start = datetime.date.fromisoformat(str(vars.get('shipped_on'))[:10])\n    eta = start + datetime.timedelta(days=3)\n    vars['delivery_day'] = eta.isoformat()\n    vars['delivery_state'] = 'known'\nexcept Exception:\n    vars['delivery_day'] = ''\n    vars['delivery_state'] = 'unknown'\n" },
            "timeout_ms": { "type": "number", "default": 10000 }
          }
        }
      }
    }
  ],
  "transitions": [
    { "target_node": "tell_delivery", "description": "always", "condition": { "operator": "always" } }
  ]
}
```

| Parameter | Meaning |
|---|---|
| `code` | The Python source, as a baked `default` string |
| `timeout_ms` | Time limit in milliseconds. Default `30000` |

### Reading and writing variables

- The snippet gets a dict named `vars`. It holds the current workflow variables.
- Read with `vars.get("name")`. A variable that was never set is absent.
- Write with `vars["name"] = value`. Every key the snippet assigns becomes a workflow variable.

Verified in a working builder:

- Call variables are in `vars`. The builder reads `vars.get("now")`, a call variable passed with the simulation.
- The result of an earlier `api_request` node is reachable from `vars` in a later code node. The builder looks for it under the mapped variable name first and under the flattened result keys second. Which of the two held the data is not recorded.
- A string written to `vars["date_facts"]` in a code node resolves as `{{date_facts}}` in the `task_message` of later conversation nodes. Multi-line strings work.
- The standard modules `json`, `re` and `datetime` can be imported.
- The same snippet can run in two code nodes at different points of the call. The later run sees the variables added in between.

### What a code node returns

Seen in a trial call: the result of a successful `code_exec` is

```json
{ "status": "success", "data": null, "message": "Code executed successfully", "status_code": 200 }
```

The snippet's output is not in `data`. Its values reach the workflow only through `vars`. After a code node named `setup` ran, the variable table held:

| Variable | Value |
|---|---|
| each key the snippet wrote, for example `date_facts` | the value, with source `tool_result` and source node `setup` |
| `setup_response.status` | `success` |
| `setup_response.data` | `null` |
| `setup_response.message` | `Code executed successfully` |
| `setup_response.status_code` | `200` |
| `setup_status_code` | `200` |
| `setup_success_count` | `1` |

For a code node the automatic keys are named after the **node**, not after `code_exec`.

### Rules for snippets

- **Do not write `{{` or `}}` in the code.** The internal sources disagree on whether the `code` field is templated. One says it is exempt. Another says placeholders are resolved when the code runs and an unset one is left as literal text, which breaks the Python. The working builder removes every `{{` and `}}` from generated code (a nested dict literal such as `{'a': {'b': 1}}` ends in `}}`) and reads all values from `vars`.
- **Never let a snippet raise.** Wrap the body in `try` and `except`, and write a fallback value for every variable that a later prompt or condition reads. A prompt that references an unset variable shows the literal placeholder to the model.
- **Write strings for routing flags**, such as `known` and `unknown`. Do not route on a Python boolean. See "Do not route on a boolean" in workflow-format.md.
- Keep snippets fast. They block the conversation.
- Do arithmetic, date calculation and counting in code, and give the model the finished facts as text. Verified in a working builder: it computes a block of date facts in a code node and places it in the prompts.
- Treat a code node like an API node: `passthrough: true`, a `passthrough_default_transition`, and a last `always` transition.

### Sandbox limits

| Limit | Value |
|---|---|
| Time | `timeout_ms`, default `30000` |
| Modules | `json`, `re` and `datetime` are verified in a working builder. The full list is not documented |
| Network and file access | Not documented |
| Memory and output size | Not documented |

### `code_exec` as a tool

`code_exec` can also be a tool in the `tools` array of a conversation node, called by the model. Its parameters are top-level arguments, declared without `default` so the model fills them. For such a tool the `code` field resolves `{{var}}` when the tool is called, against the current variable table. The working builder does not use this form, so nothing about it is verified here.

## Lifecycle tools

A tool whose `config.alwaysRunsAt` is a non-empty list is never shown to the model. The engine fires it at a fixed point of the call.

| Value | When |
|---|---|
| `start_of_call` | During call setup, before the first turn |
| `end_of_call` | After the call has ended |
| `each_turn` | Accepted by the schema but not implemented. It never fires |

Put a lifecycle tool that must run on every call into the workflow's top-level `tools` array.

```json
{
  "initial_node": "greeting",
  "nodes": {},
  "tools": [
    {
      "type": "function",
      "config": { "alwaysRunsAt": ["end_of_call"] },
      "function": {
        "name": "push_call_result",
        "handler": "__function__:api_call",
        "parameters": {
          "type": "object",
          "properties": {
            "url": { "type": "string", "default": "https://api.example.com/v1/call-results" },
            "method": { "type": "string", "default": "POST" },
            "body": {
              "type": "object",
              "properties": {
                "summary": { "type": "string", "default": "{{call.analysis.summary}}" },
                "reason": { "type": "string", "default": "{{call.call_end_reason}}" }
              }
            }
          }
        }
      }
    }
  ]
}
```

Rules:

- A workflow-level tool without `alwaysRunsAt` never runs and the model never sees it.
- A lifecycle tool in a node's `tools` runs for `start_of_call` only on the `initial_node`, and for `end_of_call` only on the node in which the call ended.
- If a `{{var}}` parameter is still unresolved, one model call fills the parameters. If everything resolves, the handler runs directly.
- `response_mapping` is applied for `start_of_call`. It is not applied for `end_of_call`.
- At the end of a call the order is: call analysis, then `end_of_call` tools, then success-criteria judging. An `end_of_call` tool can use `{{call.analysis.summary}}`, `{{call.analysis.structured_data_str}}`, `{{call.call_end_reason}}`, `{{call.call_end_reason_category}}`, `{{call.call_tags}}` and `{{call.duration}}`.
- A malformed lifecycle tool is dropped at run time without an error. Validate with a dry run (api.md).

## Tool results and the next turn

After a tool call returns, the model sees the result and has to produce the next turn itself. Two things were seen in practice runs with the hackathon's agent model:

- **The agent says nothing after the tool call.** The result arrives, no assistant message follows, and the simulated customer hangs up after waiting. It happens more often when the result is bare data such as `{"ok": true, "verified": true}`.
- **The agent ignores a negative result.** For example it reads `"verified": false` and moves on to the next question as if the answer had passed.

What fixed both in a working builder (verified, see the post-hook section above): a post-hook on the tool that adds one plain instruction line to the result before the model sees it, for example a `what_to_do_next` field that says what the answer means and what to say or call next. The model then has something to act on.

Also say it in the step's prompt: after every tool result, speak to the customer or call the next tool. Never end a turn with nothing.

## Checklist

- Fixed values use `default`, never `const`.
- Each `api_call` body field is a leaf under `body.properties` with its own `default`, `description` and `enum`.
- `tools` only on `conversation` nodes. `pre_actions` only on `api_request` and `code` nodes.
- `response_mapping` on the tool for `tools`, on the node for `pre_actions`.
- Mapping paths start with `data.`.
- Booleans from results are tested as `"true"` and `"True"`, or replaced by string fields.
- Every passthrough node ends with an `always` transition.
- Code reads and writes through `vars`, never raises, and contains no `{{` or `}}`.
- Tool descriptions say when to call the tool.
