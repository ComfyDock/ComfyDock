# Common Workflows

This page collects the tasks ComfyGit users usually come here to solve. Each
recipe points to the deeper guide when you need more detail.

## Create A Clean ComfyUI Environment

Use this when you want to test nodes or workflows without changing your main
ComfyUI install.

```bash
cg create sandbox --torch-backend auto --use
cg run
```

ComfyGit creates an isolated ComfyUI checkout and virtualenv. The selected
PyTorch backend is local to this machine and can be changed later.

Read more: [Creating environments](environments/creating-environments.md)

## Use An Existing Model Folder

Use this when you already have models under another ComfyUI installation.

```bash
cg model index dir ~/ComfyUI/models
cg model index sync
cg model index find "sdxl"
```

ComfyGit indexes the files and links environments to that model directory. It
does not duplicate model bytes.

Read more: [Model index](models/model-index.md)

## Add A Custom Node

Use registry IDs when possible:

```bash
cg node add rgthree-comfy
```

Use Git URLs when the node is not in the registry or when you need a branch,
fork, or commit:

```bash
cg node add https://github.com/example/custom-node.git@main
```

Read more: [Adding custom nodes](custom-nodes/adding-nodes.md)

## Work On A Local Node Checkout

If an environment already tracks a registry or Git node, convert the materialized
copy to your local checkout with `dev-link`:

```bash
cg node dev-link rgthree-comfy \
  --path ~/dev/rgthree-comfy \
  --replace-existing
```

That preserves the manifest identity so workflow references still point to the
same package.

Read more: [Development nodes](custom-nodes/development-nodes.md)

## Track And Resolve A Workflow

Save a workflow in ComfyUI, then inspect and resolve it:

```bash
cg workflow list
cg workflow resolve my-workflow
cg status
```

ComfyGit can detect many built-in model loader references and custom node
requirements. It will ask for help when a dependency is ambiguous.

Read more: [Workflow resolution](workflows/workflow-resolution.md)

## Add A Model The Graph Did Not Reveal

Some custom nodes load files from model folders without exposing a standard
loader widget. First make sure the file is indexed:

```bash
cg model index sync
cg model index show frame_interpolation/film_net_fp16.safetensors
```

Then declare it for the workflow:

```bash
cg workflow model add my-workflow \
  --path frame_interpolation/film_net_fp16.safetensors \
  --importance required
```

Read more: [Workflow model dependencies](workflows/model-dependencies.md)

## Add A Source Before Sharing

If a required model has no source, another machine may not be able to recreate
the environment.

```bash
cg model add-source film_net_fp16.safetensors \
  https://huggingface.co/org/repo/resolve/main/film_net_fp16.safetensors
```

Read more: [Adding model sources](models/adding-sources.md)

## Commit And Push An Environment

```bash
cg status
cg commit -m "Add Deforum workflow"
cg remote add origin git@github.com:team/deforum-env.git
cg push
```

Git stores the environment recipe and workflow files. It does not store model
bytes.

Read more: [Git remotes](collaboration/git-remotes.md)

## Import Someone Else's Environment

```bash
cg import https://github.com/team/deforum-env.git \
  --name deforum \
  --models required \
  --use
```

Import is a human setup flow. It can install Manager, prompt when needed, and
leave you with an authoring environment.

Read more: [Export and import](collaboration/export-import.md)

## Materialize A Runtime Environment

Use materialization in Docker, CI, remote machines, or runtime containers.

```bash
cg materialize https://github.com/team/deforum-env.git \
  --name deforum-runtime \
  --models required \
  --torch-backend auto \
  --replace
```

Materialize is non-interactive and does not launch ComfyUI.

Read more: [Materialize runtime environments](collaboration/materialize.md)

## Serve A Workflow Through Studio Or HTTP

First run ComfyUI:

```bash
cg run
```

Then serve the environment from another terminal:

```bash
cg serve --port 8190 --comfy-url http://127.0.0.1:8188
```

Open `http://127.0.0.1:8190` to use the packaged Studio UI.

Read more: [Serve workflows](serve-studio/serving-workflows.md)

!!! note "Media placeholder"
    Add a short clip showing `cg run`, `cg serve`, and a Studio run from one
    saved workflow contract.
