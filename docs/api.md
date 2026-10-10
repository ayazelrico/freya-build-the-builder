# REST API for builders

This page lists the calls a builder needs. The workflow JSON itself is described in [workflow-format.md](workflow-format.md) and [tools-and-code.md](tools-and-code.md).

Personas, simulations and calls are documented in full at https://docs.freyavoice.ai. Workflow creation and the workflow JSON are not documented there. Use these pages for them.

Every call on this page is taken from a client that was run against the platform, unless a line says "not confirmed".

## Basics

| Item | Value |
|---|---|
| Base URL | `https://staging-app.freyavoice.ai` |
| Auth header | `Authorization: Bearer <your API key>`. Keys start with `fak_` |
| Content type | `Content-Type: application/json` |
| User-Agent | Required, and it must look like a browser. Example: `Mozilla/5.0 (my-builder)` |

A request without a browser-like `User-Agent` is rejected before it reaches the API. The response is an HTML page with `error code: 1010`. Many HTTP libraries send a default agent that is rejected, so set the header yourself.

The curl examples use these variables:

```bash
export FREYA_API_URL=https://staging-app.freyavoice.ai
export FREYA_API_KEY=fak_your_key
export UA="Mozilla/5.0 (my-builder)"
```

### Response envelope

Every JSON response has this shape:

```json
{
  "success": true,
  "data": {
    "message": "text",
    "result": {}
  }
}
```

The payload is `data.result`. The field paths below are relative to `data.result`.

The reference client reads the wrapper keys named below (`workflow`, `simulation`, `iterations`, `workspaces`) and falls back to the bare payload if a key is missing. Do the same in your client.

An HTML response with status 404 means the route is wrong. Note that the workflow and call routes are singular (`/api/v2/workflow`, `/api/v2/call`) and the persona and simulation routes are plural.

## Workflows

### Create a workflow

`POST /api/v2/workflow`

The body holds a name and the workflow definition. The platform creates the agent together with the workflow.

```bash
curl -s -X POST "$FREYA_API_URL/api/v2/workflow" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d '{"name": "my agent", "workflow": {"initial_node": "start", "nodes": {}, "global_nodes": {}}}'
```

| Path in `result` | Meaning |
|---|---|
| `workflow.id` | The workflow id |
| `workflow.agentId` | The id of the agent that was created with it. Pass this as `agentId` to a simulation |

Put a complete workflow in `workflow`. The empty `nodes` object above only keeps the example short.

### Validate without saving (dry run)

`POST /api/v2/workflow?dryRun=true`

Same body as create. The platform runs its write validation and stores nothing.

```bash
curl -s -X POST "$FREYA_API_URL/api/v2/workflow?dryRun=true" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d @request.json
```

The fields of the dry-run result are not documented. The reference client treats any HTTP error status as a failure and prints the response body.

Validation checks the schema. It also removes fields that do not belong to a node type without reporting them. For example `pre_actions` on a `conversation` node is dropped. Read a created workflow back if you are unsure what was stored.

### Update a workflow

`PUT /api/v2/workflow/{workflowId}`

```bash
curl -s -X PUT "$FREYA_API_URL/api/v2/workflow/$WORKFLOW_ID" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d '{"workflow": {"initial_node": "start", "nodes": {}, "global_nodes": {}}}'
```

The body replaces the whole definition. A top-level key that your new definition leaves out is deleted, including `test_variables` and an `agent_config` that the platform filled in. Send the complete definition every time.

An update saves a new version and does NOT publish it. Simulations and calls run the published version, so after an update alone you are still testing the old phone agent. Publish the new version:

```bash
# newest version first
curl -s "$FREYA_API_URL/api/v2/versions/workflow/$WORKFLOW_ID?workspaceId=$WORKSPACE_ID" -H "Authorization: Bearer $FREYA_API_KEY" -H "User-Agent: $UA"
# result.versions[] has id, versionNumber, isPublished

curl -s -X POST "$FREYA_API_URL/api/v2/versions/workflow/$WORKFLOW_ID/publish" \
  -H "Authorization: Bearer $FREYA_API_KEY" -H "Content-Type: application/json" -H "User-Agent: $UA" \
  -d '{"versionId": "<id of the newest version>"}'
```

`freya.update_workflow` and `freya.save_workflow` do both steps. A run of a simulation reports the version it used as `agentVersionNumber`. Check it when a change seems to have no effect.

### Get a workflow

`GET /api/v2/workflow/{workflowId}`

```bash
curl -s "$FREYA_API_URL/api/v2/workflow/$WORKFLOW_ID" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "User-Agent: $UA"
```

The path is the same as for update. The reference client does not call this route, so the fields of its result are not confirmed.

## Workspace

`GET /api/v2/workspaces` lists the workspaces your key can see. The list is at `result.workspaces`. Each entry has an `id`.

```bash
curl -s "$FREYA_API_URL/api/v2/workspaces" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "User-Agent: $UA"
```

List routes need the workspace id as a query parameter. The name of that parameter is not confirmed here. See https://docs.freyavoice.ai.

## Personas

A persona plays the caller in a simulation. It has a prompt and success criteria.

### Create personas

`POST /api/v2/personas`

```bash
curl -s -X POST "$FREYA_API_URL/api/v2/personas" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d '{"personas": [{"name": "Late parcel", "prompt": "You are Dana Reed. Your parcel is five days late. Answer what you are asked in one short sentence.", "successCriteria": "The agent states the new delivery day.", "tags": ["practice"]}]}'
```

| Field | Meaning |
|---|---|
| `personas[].name` | Persona name |
| `personas[].prompt` | Instructions for the model that plays the caller |
| `personas[].successCriteria` | Text that the judge model checks after the call |
| `personas[].tags` | Array of strings |

The created personas are at `result.personas`, in request order. Each has an `id`.

### List personas

`GET /api/v2/personas`

```bash
curl -s "$FREYA_API_URL/api/v2/personas" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "User-Agent: $UA"
```

Not confirmed: the reference client only creates personas. The path above is the create route with `GET`. This is a list route, so it needs the workspace query parameter mentioned above. Take the parameters and result fields from https://docs.freyavoice.ai.

## Simulations

A simulation runs your agent against personas. In `chat` mode the conversation is text only.

### Create a simulation

`POST /api/v2/simulations`

```bash
curl -s -X POST "$FREYA_API_URL/api/v2/simulations" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d '{
    "agentId": "AGENT_ID",
    "name": "practice run 1",
    "mode": "chat",
    "selectedPersonaIds": ["PERSONA_ID"],
    "customerVariablesMap": {"PERSONA_ID": {"customer_id": "c_123", "first_name": "Dana"}},
    "maxConcurrentCalls": 5,
    "runsPerPersona": 1,
    "maxCallDurationSeconds": 420,
    "assistantLlmOverride": {"provider": "experimental-5", "model": "experimental-5"},
    "routingLlmOverride": {"provider": "experimental-5", "model": "experimental-5"},
    "extractionLlmOverride": {"provider": "experimental-5", "model": "experimental-5"},
    "personaLlmOverride": {"provider": "google", "model": "gemini-3-flash-preview"},
    "analysisLlmOverride": {"provider": "google", "model": "gemini-3-flash-preview"}
  }'
```

| Field | Meaning |
|---|---|
| `agentId` | `workflow.agentId` from the create call |
| `name` | Name of the simulation |
| `mode` | `"chat"` for a text simulation |
| `selectedPersonaIds` | Persona ids to run |
| `customerVariablesMap` | Object keyed by persona id. Each value is the object of call variables for that persona's call |
| `maxConcurrentCalls` | How many calls run at the same time |
| `runsPerPersona` | Calls per persona |
| `maxCallDurationSeconds` | Limit for one call |
| `assistantLlmOverride` | Model for the dialogue call. Object with `provider` and `model` |
| `routingLlmOverride` | Model for the routing call |
| `extractionLlmOverride` | Model for the extraction call |
| `personaLlmOverride` | Model that plays the caller |
| `analysisLlmOverride` | Model that judges the success criteria |

Pass all three agent overrides (`assistantLlmOverride`, `routingLlmOverride`, `extractionLlmOverride`) on every simulation. An override you leave out falls back to the agent's default model. The values above are the ones the reference client uses. Use the models your event rules name.

The simulation id is at `result.simulation.id`.

### Poll a simulation

`GET /api/v2/simulations/{simulationId}`

```bash
curl -s "$FREYA_API_URL/api/v2/simulations/$SIM_ID" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "User-Agent: $UA"
```

Read `result.simulation.status`. Poll every 10 seconds until it is `completed`, `failed` or `paused`. Other status values are not listed in the sources.

### Talk to your workflow turn by turn

`POST /api/v2/chat/message` runs one turn against the published workflow, with no simulation and no queue. It answers in seconds, so it is the fastest way to see whether a workflow starts at all and what it says first.

```bash
curl -s -X POST "$FREYA_API_URL/api/v2/chat/message" \
  -H "Authorization: Bearer $FREYA_API_KEY" -H "Content-Type: application/json" -H "User-Agent: $UA" \
  -d '{"workflowId": "'$WORKFLOW_ID'", "message": "Hello?", "customerVariables": {"customer_id": "c_test", "first_name": "Daniel", "last_name": "Reyes", "title": "Mr", "now": "2026-10-14T11:00"}}'
```

`result` has `response` (what the phone agent said) and `callId`. Send the next turn with the same `callId`. End it with `POST /api/v2/chat/end` and `{"callId": "..."}`.

Seen in tests, not guaranteed: a long turn can return 504, and when the first step is a code step the chat route may skip it, so values that step computes are empty. A bare 500 here means the workflow cannot start a call at all.

### List iterations

`GET /api/v2/simulations/{simulationId}/iterations`

```bash
curl -s "$FREYA_API_URL/api/v2/simulations/$SIM_ID/iterations" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "User-Agent: $UA"
```

An iteration is one execution of the simulation. The list is at `result.iterations`. The reference client takes the first entry's `id` right after a simulation finishes.

### Get an iteration's runs

`GET /api/v2/simulations/{simulationId}/iterations/{iterationId}`

```bash
curl -s "$FREYA_API_URL/api/v2/simulations/$SIM_ID/iterations/$ITERATION_ID" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "User-Agent: $UA"
```

`result` has `iteration`, `runs` and `runsTotal`. A run is one call with one persona.

| Field of a run | Meaning |
|---|---|
| `id` | Run id |
| `callId` | Id of the call. Use it to fetch the transcript |
| `personaId`, `personaName` | The persona that played the caller |
| `outcome` | Result of the success criteria, for example `fail` |
| `reason` | The judge's explanation |
| `turnCount` | Number of turns |
| `startedAt`, `endedAt` | Timestamps |

The route returns 30 runs unless you ask for more. Pass `limit` (100 at most) and `offset`, and read until a page comes back short. Compare the number you read with `runsTotal`. `freya.get_iteration` does this for you.

While a simulation is running, `outcome` is `queued` or `running` for the runs that have not finished.

## Calls

### Get a call with its transcript

`GET /api/v2/call/{callId}`

```bash
curl -s "$FREYA_API_URL/api/v2/call/$CALL_ID" \
  -H "Authorization: Bearer $FREYA_API_KEY" \
  -H "User-Agent: $UA"
```

The call is at `result.call`.

| Field | Meaning |
|---|---|
| `messages` | The event list of the call. See below |
| `transcript` | The conversation as one text string |
| `endedReason` | Why the call ended. For an `end_call` node it is the terminal's `function.name` |
| `duration` | Seconds |
| `successCriteriaResult` | Object with `success` and `reason` |

Each entry of `messages` has `role`, `message`, `nodeId`, `messageId` and `secondsFromStart`.

| `role` | `message` contains |
|---|---|
| `assistant` | What the agent said |
| `user` | What the caller said |
| `system` | A JSON string that describes one engine event |

System events seen in a trial call:

| `event` | Content |
|---|---|
| `node_enter` | `node`, `from_node`, `reason` |
| `function_call_start` | `function` and `args`. For an `api_call` the args are the full request: `url`, `method`, `headers`, `body` |
| `function_call_complete` | `function` and `result` |
| `route_evaluated` | `matched`, `from_node`, `target`, `reason`, a `branches` list with the result of every condition, and `variable_table` with all variables at that moment |
| `error` | `message` and `details` |

`route_evaluated` is the fastest way to learn why a transition did or did not fire. Each branch shows the variable, the operand and the result.

User and assistant messages in the trial call also carried a `workflowSnapshot` with `currentNode`, `previousNode`, `nodeTurnCount`, `totalTurnCount`, `transitionHistory`, `enteredNodes` and `variableTable`. Each entry of `variableTable` has `value`, `confidence`, `source` and `source_node`. Whether a query parameter is needed to receive the snapshots is not confirmed.

To check whether a variable arrived, read `variable_table` or `variableTable`. Finding the variable's name in a prompt or in a code body proves nothing about its value.

## A minimal loop

1. Build the workflow JSON.
2. `POST /api/v2/workflow?dryRun=true` and fix what it rejects.
3. `POST /api/v2/workflow`. Keep `workflow.agentId`.
4. `POST /api/v2/personas` once. Keep the ids.
5. `POST /api/v2/simulations` with the agent id, the persona ids and the call variables.
6. Poll `GET /api/v2/simulations/{id}` until the status is final.
7. `GET .../iterations`, then `GET .../iterations/{id}` for the runs.
8. For each failed run, `GET /api/v2/call/{callId}` and read the events.

For everything else, see https://docs.freyavoice.ai.
