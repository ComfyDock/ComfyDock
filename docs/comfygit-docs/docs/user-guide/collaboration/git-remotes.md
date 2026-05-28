# Git Remotes

Git remotes let a team share environment history. The remote stores the
environment recipe, not model bytes.

## Add A Remote

```bash
cg remote add origin git@github.com:team/my-env.git
cg remote list
```

## Push

```bash
cg push
```

Choose a remote explicitly:

```bash
cg push -r origin
```

## Pull

```bash
cg pull
```

Choose a remote and model strategy:

```bash
cg pull -r origin --models required
```

Preview or resolve conflicts:

```bash
cg pull -r origin --preview
cg pull -r origin --auto-resolve theirs
```

After pull, ComfyGit reconciles runtime state toward the pulled manifest and
your local runtime configuration.

## Branches

```bash
cg branch experiment
cg switch experiment
cg push -r origin
```

Use branch names to collaborate on environment changes before merging them.

## Models And Remotes

Git does not carry model bytes. Before pushing an environment for another user,
make sure required model dependencies have source information:

```bash
cg status
cg model add-source model.safetensors URL
cg commit -m "Add model source"
cg push
```

## Workflow Contracts

If a workflow has a saved contract, make sure the referenced `workflow_api/`
artifact is committed along with the workflow and manifest.

Missing API prompt artifacts make served contracts incomplete.
