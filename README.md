# AutoShotgun (Custom Deadline Event Plugin)

AutoShotgun is a custom Deadline event plugin that creates and updates Autodesk Flow Production Tracking (ShotGrid) `Version` entities when eligible render jobs finish.

This implementation is highly studio-specific and built around an internal pipeline naming convention. It assumes Deadline-generated outputs follow strict naming/abbreviation patterns and folder structure rules, so files can be automatically classified and linked to the correct ShotGrid Project / Shot or Asset / Task / User context

## What This Plugin Does

When a Deadline job finishes, the plugin:

1. Checks whether the job is an AutoDraft-created job (by comment text).
2. Reads output paths from job output directories/files.
3. Infers pipeline context from the output folder structure:
   - project
   - shot/asset
   - pipeline step
4. Resolves the ShotGrid user login from:
   - Deadline `job.UserName`
   - `AUTOSHOTGUN_LOGIN_SUFFIX` loaded from local `.env`
5. Searches ShotGrid for matching:
   - Project
   - Shot or Asset
   - Task assigned to that user (preferably by step match)
6. Creates a `Version` if one with the same code does not already exist on that entity.
7. Uploads media to the created/found version:
   - movie (`.mov` / `.mp4`) when present
   - otherwise first frame from sequence-style output

## High-Level Processing Flow

### 1) Event Trigger

- Entry point: `OnJobFinished` in `AutoShotgun.py`.
- Runs only for jobs whose comment contains:
  - `Job Created by AutoDraft`

### 2) ShotGrid API Setup

- `ConfigureShotgun()` validates local API path:
  - `custom/events/AutoShotgun/shotgun_api3`
- Adds plugin folder to Python path and imports `shotgun_api3`.
- Uses settings from the `Shotgun` event plugin config (URL, Script Name, Script Key, mappings, etc.).

### 3) Context Discovery From Output Path

- Reads `job.JobOutputDirectories` and `job.JobOutputFileNames`.
- Assumes output directory structure encodes:
  - project name
  - shot/asset name
  - pipeline step
- Performs normalized name matching (ignores spaces, `_`, `-`, case).

### 4) Entity and Task Matching

- Gets active projects and candidate tasks from ShotGrid via `AutoShotgunUtils.py`.
- Locates matching project.
- Within project, tries to match shot first; if not found, tries asset.
- Then attempts to find a task:
  - same project
  - same entity (shot/asset)
  - step name starts with parsed pipeline step
- If no task is found, creates version without task linkage.

### 5) Version Metadata Assembly

- Version code is derived from output filename (without extension).
- Description is fixed to: `Created by Autoshotgun`.
- Frame range uses job frames or `FrameRangeOverride` if valid.
- Frame path is extracted from Draft args (`ScriptArg13` -> `inFile="..."`), then padding is normalized with `ReplacePadding()`.

### 6) Create or Reuse Version

- Checks existing versions on target entity by `code`.
- If found, reuses that version ID (no duplicate create).
- If not found, creates new Version using:
  - `AddNewVersion()` (with task)
  - or `AddNewVersionNoTask()` (without task)

### 7) Upload Output Media

- If output is movie (`.mov`, `.mp4`), uploads movie to the version.
- Otherwise tries a still from sequence output and uploads that file.

## Repository Files

- `AutoShotgun.py`  
  Deadline event listener and end-to-end job-finished workflow.

- `AutoShotgunUtils.py`  
  ShotGrid API helpers (auth/session, entity queries, version create/update/upload).

- `AutoShotgun.param`  
  Event plugin parameters for this custom plugin.

- `Shotgun_full_version.param`  
  Full parameter schema/reference for ShotGrid plugin-style mappings and options.

- `.env.example`  
  Local environment template used by this custom plugin.

## Configuration

### 1) Deadline Event Configuration

Configure required ShotGrid connection and field mapping keys in the Shotgun event config used by helper utilities, especially:

- `ShotgunURL`
- `ShotgunScriptName`
- `ShotgunScriptKey`
- `ShotgunStatusList`
- Version field mappings (`VersionEntity*`)

### 2) Local `.env` (AutoShotgun folder)

Copy `.env.example` to `.env` and set:

- `AUTOSHOTGUN_LOGIN_SUFFIX` (required by current implementation)

Notes:

- `.env` is local-only and should stay out of git.
- `DEFAULT_PASSWORD` exists in `.env.example`, but this code path does not currently consume it in `AutoShotgun.py`.

## Expected Output Path Convention

Current matching logic expects structured output folders that allow parsing:

- project
- shot/asset
- pipeline step

In this setup, the Deadline output naming scheme and shorthand conventions are part of the integration contract. The plugin relies on these conventions to perform deterministic segregation and matching across projects, shots/assets, tasks, and users.

If your studio folder structure or naming abbreviations differ, update parsing/matching logic in `CreateShotgunVersion()` accordingly.
For adaptation to other studios/pipelines, please contact the maintainers for further customization.

## Error Handling and Logging

- Plugin logs through Deadline event logging (`LogInfo` / `ClientUtils.LogText`).
- Most failures are non-fatal for Deadline job completion; they stop ShotGrid sync for that job and log details.
- Verbose traceback behavior is controlled by code/config paths (`verboseLogging` and event config conventions).

## Limitations / Assumptions

- Trigger currently depends on exact AutoDraft comment marker.
- Path parsing depends on fixed folder segment positions.
- Version code uniqueness is checked only by code within target entity.
- Task matching prefers step prefix comparison and may require pipeline naming consistency.


## License

Internal custom pipeline plugin (license not specified in repository).
