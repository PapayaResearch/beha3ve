# Examples

Run all examples from this directory after [installation](README.md#installation). Each task in `conf/task/` includes its intervention and run defaults.

See the [example catalog](website/content/docs/reference/example-catalog.mdx) for the full task list, prerequisites, and outcomes.

## Browser research

Wikipedia task with and without an HTML banner:

```bash
python run.py task=examples/live_wikipedia_research
uv run view runs/live_wikipedia_research
```

## Shopping cues

ABxLab-derived *One Stop Market* product choice task with social-proof, scarcity, and authority cues. To add a variation, copy one file in `conf/task/abxlab/abx_*.yaml`, change `task.id`, and edit its intervention. Override `task.instruction` or `task.fixture.start_urls` there to change the task; `_camera_choice.yaml` supplies the remaining defaults.

```bash
python run.py -m task=abxlab/abx_social_proof,abxlab/abx_scarcity,abxlab/abx_authority hydra.sweep.dir=runs/abxlab-minimal 'hydra.sweep.subdir=${experiment_id}'
uv run view runs/abxlab-minimal
```

## Native desktop cues

Copy a draft in OSWorld-V2, with Draft B preselected in treatment. Requires a running desktop and a vision model:

```bash
python run.py task=osworld/native_default
uv run view runs/native_default
```

Set `OSWORLD_ENDPOINT` in `.env` to your desktop service URL.

## Single and factorial runs

One authority condition, without a control episode:

```bash
python run.py task=abxlab/single_authority hydra.run.dir=runs/design-examples/single
```

A 2×2 design crosses displayed price ($399 / $249) with a neutral / authority subtitle on the first camera. It runs all four combinations:

```bash
python run.py task=abxlab/factorial_camera hydra.run.dir=runs/design-examples/factorial
uv run view runs/design-examples
```

The viewer lets you compare conditions that differ in one factor. `artifacts/factorial_contrasts.json` contains numeric main effects averaged over the other factor; it does not estimate interactions or uncertainty. One run per combination demonstrates the mechanics, not a reliable behavioral effect. Prices are edited in the displayed page, not the store's checkout database.

`single` runs one selected condition. `factorial` saves you enumerating combinations and computes main effects; use `paired` when there is just one treatment to compare with control.
