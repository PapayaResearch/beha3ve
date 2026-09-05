# Bring Your Own Benchmark

Here, we assume that you will bring your own tasks, environment, and experiment design. The harness will run the agent under each condition and log the evidence for your analysis.

Start with one file in `conf/task/`. Put the instructions, starting setup, outcomes, and `intervention` under `task:`. Select the environment and design in that file’s Hydra defaults and include any agent or run settings there too. Add your own Python module when you need custom behavior. Separate config files are optional and useful when several experiments share the same settings.

## tl;dr

For your benchmark, start with the edit points given below (all paths relative to this directory):

| Edit point | Content |
|---|---|
| `scripts/generate_experiments.py` | Generate case overrides from CSV columns containing dotted config paths |
| `integrations/` | Benchmark-specific setup, drivers, interventions, and outcomes, including the shipped examples |
| `conf/task/` | Start here: task definition, intervention, outcomes, action budget, and default run settings |
| `conf/environment/` | Backend connection, setup/state callbacks, observation settings, and supported actions |
| `conf/agent/` | Model profiles and LiteLLM request arguments (`chat_model_args`) |
| `conf/agent/_shared.yaml` | Shared prompts, tools, memory, observations, and agent implementation |
| `conf/experiment/` (optional) | Create this directory if you want named overrides for task defaults |
| `conf/design/` | Single/paired/factorial design, matching fields, repetitions, and condition order |
| Hydra `hydra/launcher` config | Parallel multiruns via a Hydra launcher plugin; conditions within a run execute serially |
| `conf/config.yaml` | Shared defaults, seed, action budget, and output paths |
| `.env` | Local model credentials and environment URLs (.gitignore'd) |
| `pyproject.toml` | Additional dependencies and package/CLI entry points; update `uv.lock` when dependencies change |

If you need to change how the harness works, there are also:

| Edit point | Content |
|---|---|
| `run.py` | Configuration composition, agent/environment construction, condition execution, and result writing |
| `harness/runner.py` | Episode loop, stopping, and multi-agent turn scheduling |
| `harness/html.py` | Local BrowserGym-derived HTML pruning and retained attributes |
| `harness/agents.py` | Model requests, prompts, memory, observation formatting, and action parsing |
| `harness/environments/driver.py` | Custom-driver interface, `Frame`, and HTTP service connection |
| `harness/environments/browser.py` | Browser lifecycle, navigation, actions, observations, and response interception |
| `harness/environments/osworld_server.py` | Existing OSWorld server connection, GUI actions, and screenshots |
| `harness/environments/osworld.py` | Optional older OSWorld SDK lifecycle and evaluator integration |
| `harness/environments/computer_use.py` | Computer-use adapter and in-memory desktop backend |
| `harness/environments/structured.py` | Actors, messages, shared state, provenance, and policy decisions |
| `harness/environments/base.py` | Shared adapter behavior, capabilities, and backend events |
| `harness/interventions.py` | Intervention selection, ordering, validation, and application records |
| `harness/transforms/` | Reusable text, visual, structured, browser, and agent edits |
| `harness/design.py` | Build conditions and factor combinations |
| `harness/evaluators.py` | Outcome evaluation and paired/factorial numerical summaries |
| `harness/schema.py` | Shared observation, action, transition, and snapshot fields |
| `harness/artifacts.py`, `serialization.py` | Saved records, binary artifacts, hashes, and serialization |
| `harness/replay.py`, `replay_run.py` | Read trajectories, mask observer views, and create supported handoff branches |
| `inspect_run.py` | CLI summaries of saved runs |
| `harness/trace_viewer.py` | Load saved episodes, group comparisons, and serve the viewer |
| `harness/viewer/` | Viewer layout, navigation, styles, themes, and help text |
| `harness/integration.py`, `templates/` | Generated integration files and the model-free integration checker |
| `harness/testing.py`, `tests/` | Scripted agents, fixtures, and checks for your changes |
| Package `__init__.py` files | Public imports when you expose new reusable components |
| `.pre-commit-config.yaml`, `.gitignore` | Development checks and exclusion of local/generated files |

## Step 1: Defining the agent task

We recommend beginning with task instructions and cases you want to evaluate (likely coming from some study-specific data). You will need to decide what the agent can do, a stopping rule, and a decision rule for successful trajectories.

Put a `task:` section in `conf/task/<name>.yaml`, with `# @package _global_` at the top so the file can also set environment, agent, and design defaults. Run it with `python run.py task=<name>`. Its fields include:

| Field | Content |
|---|---|
| `id`, `fixture_version` | Task identity and a version for its setup |
| `max_steps` | Task action budget, normally 10; the run inherits this value |
| `modality` | What the agent receives: `pruned_html`, `accessibility_tree`, `screenshot`, `text`, or a list combining them |
| `instruction` | The goal presented to the agent |
| `fixture` | Data passed to environment reset, such as a case ID or starting URL |
| `available_actions` | Action names, arguments, and descriptions the agent receives |
| `required_capabilities` | Environment features the task needs |
| `outcomes` | Functions that measure what happened |
| `held_fixed` | Notes on what you intend to keep unchanged |
| `factors` | Factors for a factorial design, or `[]` for a simple pair |

Browser observations include a hierarchical accessibility snapshot and actionable element IDs. `pruned_html` removes scripts, styles, comments, and presentation attributes while retaining action IDs and form values. Pruning happens after observation interventions. Choose `screenshot` for visual-only page or desktop content; instructions, step context, and action history still accompany it. `text` includes visible text and structured context. `agent.spec.config.max_observation_chars` limits the observation text sent per call.

The viewer defaults to **Screenshot**. A small **Agent input** indicator marks matching observation tabs; unmatched representations, such as pruned HTML, get an **Agent input** tab at the end. The full recorded request is always available under **Model input and output**. Older traces without modality metadata use the last tab and are labeled as legacy.

You can reuse one task definition across many cases if needed. You should include your case ID in `design.pair_on` so the harness can automatically match control and treatment within each case (plan to update `fixture_version` when the setup, scoring rule, etc. changes).

## Step 2: Connecting to the environment

Your environment needs to reset cases, provide observations, and handle action execution. We provide a few starting points:

| You have… | Start with… |
|---|---|
| Website | The Playwright backend; add application setup and a state reader |
| OSWorld-style desktop | `OSWorldServerDriver` |
| Another desktop or simulator SDK | Your own driver implementing `reset`, `step`, and `close` |
| Another service | `HTTPDriver`, implementing session-based `/reset`, `/step`, and `/close` endpoints |

`uv run integrate new <NAME> --kind browser`, `--kind computer`, or `--kind custom` will create one task YAML containing the task and environment settings. Supply `--url` for a website or `--endpoint` for an HTTP service; these are saved in `.env` and referenced by the generated YAML. The custom option will also create a driver module.

Put your Python code in `integrations/` and reference its functions using dotted import paths in YAML, and the harness can then load them directly.

For browsers, some useful callbacks are `setup(context, options, seed)` and `state_reader(page)`. The former handles any preparation for the session before navigation, and the state reader retrieves the application state after reset and actions (note: you may still need to reset shared server-side data depending on the environment).

For a custom driver, `reset(seed, options)` and `step(action)` will return a [`Frame`](harness/environments/driver.py). Its `text`, `structured`, and screenshot fields are agent observations, and its `state` is primarily intended to be used as evidence for evaluation.

## Step 3: Adding interventions

You must first decide what exactly your intervention intervenes on, in addition to where it happens and what aspects should remain fixed. Put the specification under `task.intervention.specs` in the same task file:

| Field | Content |
|---|---|
| `scope`, `target`, `modality` | Whether you edit the environment, agent, or observer view, and what kind of data you edit |
| `hook` | When the edit occurs |
| `function`, `arguments` | Your Python function and its parameters |
| `selector` | Which cases, pages, or events it applies to |
| `max_applications` | Optional per-episode limit |
| `held_fixed_fields` | Fields that should remain unchanged |

An intervention function receives `(value, context, **arguments)` and returns [`InterventionResult`](harness/interventions.py) containing the edited value and `changed_fields`. Note that the `held_fixed` list is descriptive only, to be used for downstream analysis or record-keeping.

You should configure the timing based on your research question, e.g. `navigation_response` will edit browser HTML before rendering; `episode_start` can change reset options consumed by a desktop driver; `observation` will change what is delivered to the agent, and `agent_build` will modify its configuration before construction.

## Step 4: Configuration the agent and experimental design

Your task file includes the default environment, agent settings, and design. An experiment file is optional; create `conf/experiment/<name>.yaml` with `# @package _global_` and the overrides you need, then select it with `experiment=<name>`. Use `paired` for a control/treatment comparison, `factorial` for combinations of configured factor levels, or `single` for one condition. Set repetitions, seeds, and case matching in the task file. `max_steps: ${task.max_steps}` at the run level inherits the task’s action budget; experiment or CLI overrides can change it. To run control alone, use `design=single design.conditions=[control]`; for treatment alone, use `design=single`.

The agent settings are useful for configuring the model, prompt, tools, observation format, and memory, via `agent.chat_model_args` for model request parameters, `agent.spec.config` for observation and action formatting, and `agent.spec.memory_policy` for history. Shared defaults live in `conf/agent/_shared.yaml`; select a model with `agent=<profile>`. Shared settings will affect both arms, but you can use an `agent_build` intervention when the agent setting itself is intended to be a treatment.

If you bring your own agent, point `agent.spec.scaffold._target_` at the relevant class. It needs `reset(seed)` and `act(observation)`. With `accepts_spec: true`, the constructor will also receive the agent specification and configuration arguments.

Conditions within a run execute serially. Use Hydra multiruns and `hydra/launcher` for parallel tasks or seeds. Each parallel job needs an independent environment if the service holds shared state, such as an OSWorld desktop.

## Step 5: Analyzing evidence

You should write outcome functions so that they receive `(trajectory, state, **arguments)`. Return a value or an [`Outcome`](harness/evaluators.py) with evidence; reference functions under `task.outcomes`.

We suggest considering how to cleanly separate your measurement of behavior from that of task completion. For example, you may want to use the actual application state to establish success. You may also need to think of how to represent missing data, failures, etc. before collecting runs for analysis.

It may be useful to begin by inspecting one pair (e.g. using the viewer). Review the starting case, the intervention, the actions, and the final state. `design.require_intervention_application` can help to reject treatments that did not change the target, but this does not itself guarantee that the cue was visible to the agent. Then, you can expand to your case sample and repeated runs. The harness will store trajectories, model calls, interventions, snapshots, and outcomes. Depending on the task, control and treatment trajectories can also diverge in length (the viewer supports unlinking to make this easy to inspect). Your analysis will determine how to aggregate across cases and quantify uncertainty.

## Modifying the harness itself

Most integrations can stay in your module and YAML. If your proposal needs more, these are the relevant entry points:

| You need to change… | Edit point |
|---|---|
| Browser actions, observations, or interception | [environments/browser.py](harness/environments/browser.py) |
| Desktop connection and action execution | [environments/osworld_server.py](harness/environments/osworld_server.py) |
| Driver interface or additional backend events | [environments/driver.py](harness/environments/driver.py), [environments/base.py](harness/environments/base.py) |
| Model calls, prompts, memory, or parsing | [agents.py](harness/agents.py) |
| Actor observations and message delivery | [environments/structured.py](harness/environments/structured.py) |
| Multi-agent turn scheduling | `ScheduledEpisodeRunner` in [runner.py](harness/runner.py) |
| Saved observer views or resumable branches | [replay.py](harness/replay.py) |
