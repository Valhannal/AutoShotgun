from __future__ import absolute_import
from System.Diagnostics import *
from System.IO import File, Path
from System import TimeSpan

import re
import sys
import traceback
import os
import shutil
import importlib
from datetime import datetime
import subprocess
import time

try:
    from typing import Optional
except ImportError:
    pass

from Deadline.Jobs import Job
from Deadline.Events import DeadlineEventListener
from Deadline.Scripting import ClientUtils, FrameUtils, PathUtils, RepositoryUtils, StringUtils, SystemUtils

# Add the events folder to the PYTHONPATH so that we can import ShotgunUtils.
shotgunUtilsPath = RepositoryUtils.GetEventPluginDirectory("AutoShotgun")
if not shotgunUtilsPath in sys.path:
    sys.path.append(shotgunUtilsPath )

import AutoShotgunUtils
importlib.reload(AutoShotgunUtils)
verboseLogging = False

def _load_dotenv(dotenv_path):
    """
    Minimal .env loader (no external deps).
    Supports: KEY=VALUE, quotes, and ignores comments/blank lines.
    """
    try:
        if not dotenv_path or not os.path.exists(dotenv_path):
            return

        with open(dotenv_path, "r") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # Never fail the event plugin due to local env parsing.
        return

def GetDeadlineEventListener():
    # type: () -> ShotgunEventListener
    return ShotgunEventListener()

def CleanupDeadlineEventListener(eventListener):
    # type: (ShotgunEventListener) -> None
    eventListener.Cleanup()

class ShotgunEventListener( DeadlineEventListener ):
    def __init__(self):
        if sys.version_info.major == 3:
            super().__init__()
        # type: () -> None
        self.OnJobFinishedCallback += self.OnJobFinished

    def Cleanup(self):
        # type: () -> None
        del self.OnJobFinishedCallback

    def ConfigureShotgun(self):
        # type: () -> str
        shotgunPath = RepositoryUtils.GetRepositoryFilePath("custom/events/AutoShotgun", True)
        shotgunApiPath = os.path.join(shotgunPath, "shotgun_api3")

        if not os.path.exists(shotgunApiPath):
            self.LogInfo(f"ERROR: Could not find Shotgun API at expected location '{shotgunApiPath}'")
            return ""

        self.LogInfo(f"Importing Shotgun API from '{shotgunApiPath}'...")
        if shotgunPath not in sys.path:
            sys.path.append(shotgunPath)

        # Log Python environment information
        self.LogInfo(f"Python executable: {sys.executable}")
        self.LogInfo(f"Python version: {sys.version}")

        for attempt in range(3):  # Try twice
            try:
                # Attempt to import shotgun_api3
                import shotgun_api3.shotgun
                self.LogInfo(f"Successfully imported shotgun_api3 from {shotgun_api3.__file__}")
                return shotgunPath
            except ImportError as e:
                self.LogInfo(f"ImportError: {e}")
                if attempt == 0:
                    self.LogInfo("Retrying import after 5 seconds...")
                    time.sleep(35)
                else:
                    self.LogInfo("Failed to import after retry. Please check the network path and permissions.")
            except Exception as e:
                self.LogInfo(f"An error occurred while trying to connect to Shotgun: {str(e)}")
                self.LogInfo(traceback.format_exc())
                break

        return ""

    def CreateShotgunVersion(self, job, shotgunPath):
        # type: (Job, str) -> Optional[str]
        global verboseLogging

        # Check the necessary Shotgun info
        ##############################################################################################
        outputDirectories = job.JobOutputDirectories
        outputFilenames = job.JobOutputFileNames

        if not outputDirectories or not outputFilenames:
            ClientUtils.LogText("No output directories or filenames found.")
            return None

        for i in range(len(outputDirectories)):
            draftOutputDir = outputDirectories[i]
            draftOutputFile = outputFilenames[i]
            draftOutputPath = os.path.join(draftOutputDir, draftOutputFile)

            if not os.path.exists(draftOutputPath):
                ClientUtils.LogText(f"Draft output file does not exist: {draftOutputPath}")
                continue
            self.LogInfo(f"Draft output directory is '{draftOutputDir}'")
            self.LogInfo(f"Draft output file is '{draftOutputFile}'")
        self.LogInfo("Finished checking draft output paths.")

        # GET project info from Draftoutput directory
        output_Draft_dir = draftOutputDir.replace('[\]', os.sep)
        parts = [part for part in output_Draft_dir.split(os.sep) if part]
        project_name = parts[1]
        shot_asset_name = parts[2]
        pp_step = parts[3]
        self.LogInfo(f"Project - {project_name}, Shot/Asset - {shot_asset_name}, Pipeline step - {pp_step}")

        # Get user login info
        _load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
        login_suffix = os.environ.get("AUTOSHOTGUN_LOGIN_SUFFIX", "").strip()
        if not login_suffix:
            self.LogInfo("ERROR: Missing AUTOSHOTGUN_LOGIN_SUFFIX in AutoShotgun .env file.")
            return None
        default_username = f"{job.UserName}{login_suffix}"
        self.LogInfo(f"USERNAME is - {default_username}")

        config = RepositoryUtils.GetEventPluginConfig('AutoShotgun')
        draftField = config.GetConfigEntry('DraftTemplateField')

        import AutoShotgunUtils
        importlib.reload(AutoShotgunUtils)
        # Get a single instance of Shotgun and use it throughout
        AutoShotgunUtils.GetShotgun(shotgunPath)
        tasks = AutoShotgunUtils.GetTasks(default_username, draftField, shotgunPath)
        projects = AutoShotgunUtils.GetProjects(shotgunPath)
        #old, before using caching shotgrid
        #tasks = AutoShotgunUtils.GetTasks(DEFAULT_USERNAME, draftField, sg_instance)
        #projects = AutoShotgunUtils.GetProjects(sg_instance)

        found_task = None
        found_shot = None
        found_asset = None
        found_project = None

        # Look for a project
        for project in projects:
            formatted_project_name = project_name.replace(' ', '').replace('_', '').replace('-','').lower()
            formatted_project = project['name'].replace(' ','').replace('_', '').replace('-','').lower()
            #print(f"formatted_project_name: {formatted_project_name}")
            #print(f"formatted_project: {formatted_project}")
            if formatted_project_name in formatted_project:
                self.LogInfo(f"Project '{project_name}' is on Flow/Shotgrid with id {project['id']}")
                found_project = project
                
                # Only fetch shots and assets after finding a matching project
                shots, assets = AutoShotgunUtils.GetShotsAndAssets(project['id'], shotgunPath)

                 # Look for a shot
                if shots != '':
                    for shot in shots:
                        formatted_shot_asset_name = shot_asset_name.replace(' ', '').replace('_', '').replace('-','').lower()
                        formatted_shot_code = shot['code'].replace(' ', '').replace('_', '').replace('-', '').lower()
                        if formatted_shot_asset_name in formatted_shot_code:
                            self.LogInfo(f"Shot '{shot_asset_name}' is in the project with id {shot['id']}")
                            found_shot = shot

                            # Look for a task in a shot by task name
                            for task in tasks:
                                if (task['project']['name'] == project['name'] and 
                                task['entity']['name'] == shot['code'] and
                                task['step']['name'].strip().lower().startswith(pp_step.lower())):
                                    print(f' Check task step == stepname {task["step"]["name"]} == {pp_step}')
                                    self.LogInfo(f"For user {job.UserName} found task '{task['content']}' in this shot with id {task['id']}")
                                    found_task = task
                                    break
                            if found_task:
                                break
                if found_task:
                    break

                # Look for an asset
                if assets !='' and not found_task:
                    for asset in assets:
                        if shot_asset_name.replace(' ', '').replace('_', '').replace('-','').lower() in asset['code'].replace(' ', '').replace('_', '').replace('-','').lower():
                            self.LogInfo(f"Asset '{shot_asset_name}' is in the project with id {asset['id']}")
                            found_asset = asset
                            # Look for task in an asset
                            for task in tasks:
                                if task['project']['name']==project['name'] and task['entity']['name']==asset['code']:
                                    self.LogInfo(f"For user {job.UserName} found task '{task['content']}' in this asset with id {task['id']}")
                                    found_task = task
                                    break
                            if found_task:
                                break
                # Break out of project loop once we've processed the matching project
                break

        if not found_project:
            self.LogInfo('No project found. No Version has been created')
            return None
        if not found_shot and not found_asset:
            self.LogInfo('No shot and asset found. No Version has been created')
            return None
        if found_task:
            self.LogInfo(f"Version with task id {found_task['id']}")
        else:
            self.LogInfo('No task found, create version without task')
            found_task = {'id': ''}

        ##############################################################################################

        # Create new version
        try:
            # Pull the necessary Shotgun info.
            userName = default_username
            if found_task:
                taskId = found_task['id']
            else:
                taskId = None  # Set taskId to None or an empty string if no task is found.
            projectId = found_project['id']
            if found_shot:
                entityId = found_shot['id']
                entityType = 'Shot'
            elif found_asset:
                entityId = found_asset['id']
                entityType = 'Asset'
            else:
                self.LogInfo(f"There is no shot or asset with the name '{shot_asset_name}'. No version has been created")
                return None # Exit the function if neither shot nor asset is found


            """ # Versions autonaming
            #Find latest version for this task or shot. Set new version automatically
            versions = AutoShotgunUtils.GetVersions(entityType, entityId, shotgunPath)

            def extract_version_number(version_code):
                match = re.search(r'(\d+)$', version_code)
                if match:
                    return int(match.group(1))
                else:
                    return 0

            sorted_versions = sorted(versions, key=lambda v: extract_version_number(v['code']))
            # Get the last version
            if sorted_versions:
                last_version = sorted_versions[-1]['code']
                match = re.search(r'(.*?)(\d+)$', last_version)
                if match:
                    base_name = match.group(1)
                    last_version_number = int(match.group(2))
                    new_version_number = last_version_number + 1
                    new_version_code = f"{base_name}{new_version_number:03d}"
                else:
                    base_name = last_version
                    new_version_code = f"{base_name}_001"
                else:
                new_version_code = "v_001"
            print(f"New version code: {new_version_code}")
            """

            version = os.path.splitext(draftOutputFile)[0]      #Version code is output file
            #description = job.Name
            description = 'Created by Autoshotgun'
            frames = job.JobFramesList
            frameRangeOverride = job.GetJobExtraInfoKeyValue("FrameRangeOverride")
            if not frameRangeOverride == "" and FrameUtils.FrameRangeValid(frameRangeOverride):
                frameString = frameRangeOverride
                inputFrameList = frameRangeOverride
                frames = FrameUtils.Parse(inputFrameList)
            frameCount = len(frames)
            frames = FrameUtils.ToFrameString(frames)

            # Extract frame sequence path from ScriptArg13
            script_args = job.GetJobPluginInfoKeyValue('ScriptArg13')

            outputPath = None
            # Use regex to find the inFile parameter if ScriptArg13 is provided
            if script_args:
                match = re.search(r'inFile="([^"]+)"', script_args)
                if match:
                    outputPath = match.group(1)
                else:
                    self.LogInfo('Frame sequence path not found in ScriptArg13.')
            else:
                self.LogInfo('ScriptArg13 not found in job plugin info.')
            # If outputPath is None, handle the missing information appropriately
            if not outputPath:
                self.LogInfo('No frame sequence path provided. Defaulting to movie output path for frames.')
                outputPath = draftOutputPath  # Fallback to the movie path if no frames path is found

            # Use ShotgunUtils to replace padding in output path
            framePaddingCharacter = self.GetConfigEntryWithDefault("FramePaddingCharacter", "#")
            outputPath = AutoShotgunUtils.ReplacePadding(outputPath, framePaddingCharacter)
            self.LogInfo("Output path to frames: " + outputPath)
        except:
            if verboseLogging:
                raise
            else:
                self.LogInfo("An error occurred while retrieving Shotgun info from the submitted Job. No Version has been created.")
                self.LogInfo(traceback.format_exc())
                return None

        versionId = None
        #Chek if already exists version with this name in shot/asset
        exist_versions = AutoShotgunUtils.GetVersions(entityType, entityId, shotgunPath)
        for current_version in exist_versions:
            if current_version['code']==version:
                versionId = current_version['id']
                print(f'There is already version with code {version}. Pass to create new version, use exist versionId {versionId}')
                break
        if versionId is None:
            # Create new version
            try:
                # Use ShotgunUtils to add a new version to Shotgun.
                import AutoShotgunUtils
                importlib.reload(AutoShotgunUtils)

                self.LogInfo("Adding new version with the following settings:")
                self.LogInfo(f"userName={default_username}")
                self.LogInfo(f"taskId={taskId if taskId else ' No Task ID '}")
                self.LogInfo(f"projectId={projectId}")
                self.LogInfo(f"entityId={entityId}")
                self.LogInfo(f"pipelineStep={pp_step}")
                self.LogInfo(f"entityType={entityType}")
                self.LogInfo(f"version={version}")
                #self.LogInfo(f"description={job.Name}")
                self.LogInfo(f"description= Created by Autoshotgun")
                self.LogInfo(f"frames={frames}")
                self.LogInfo(f"frameCount={frameCount}")
                self.LogInfo(f"outputPath={outputPath}")
                self.LogInfo(f"shotgunPath={shotgunPath}")
                self.LogInfo(f"job.JobId={job.JobId}")
                if taskId:
                    newVersion = AutoShotgunUtils.AddNewVersion(userName, taskId, projectId, entityId, entityType, version,
                                                        description, frames, frameCount, outputPath, shotgunPath,job.JobId)
                else:
                    newVersion = AutoShotgunUtils.AddNewVersionNoTask(userName, projectId, entityId, entityType,version,
                                                        description, frames, frameCount, outputPath,shotgunPath, job.JobId)
                versionId = newVersion['id']
                self.LogInfo("Created new version in Shotgun with ID " + str(versionId) + ": " + version)
                # Save the version ID with the job for future events.
                job.SetJobExtraInfoKeyValue("VersionId", str(versionId))
                RepositoryUtils.SaveJob(job)
            except:
                if verboseLogging:
                    raise
                else:
                    self.LogInfo("An error occurred while attempting to add a new Version to Shotgun. No Version has been created.")
                    self.LogInfo(traceback.format_exc())
                    return None
        return versionId


    def OnJobFinished(self, job):
        # type: (Job) -> None
        global verboseLogging
        # Make sure we have the latest job info
        shotgunPath = self.ConfigureShotgun()

        if shotgunPath != "":
            self.LogInfo("  shotgun path is '%s'..." % shotgunPath)
            import AutoShotgunUtils

        try:
            # Check if the job was created by AutoDraft
            if "Job Created by AutoDraft" in job.Comment:
                self.LogInfo(f"Run CreateShotgunVersion function")
                versionId = self.CreateShotgunVersion(job, shotgunPath)
                if versionId is not None and versionId != '':
                    outputDirectories = job.JobOutputDirectories
                    outputFilenames = job.JobOutputFileNames

                    if len(outputFilenames) == 0:
                        raise Exception("ERROR: Could not find an output path in Job properties, no movie will be uploaded to Shotgun.")

                    # Use the first output directory and filename
                    base_path = outputDirectories[0]  # Use the first output directory
                    base_filename = outputFilenames[0]  # Use the first output filename

                    # Check if the filename has a movie extension
                    if base_filename.lower().endswith(('.mov', '.mp4')):
                        movie_path = os.path.join(base_path, base_filename)
                        if os.path.exists(movie_path):
                            self.LogInfo("Uploading movie: " + movie_path)
                            AutoShotgunUtils.UploadMovieToVersion(int(versionId), movie_path, shotgunPath)
                        else:
                            self.LogInfo(f"ERROR: movie file is missing: {movie_path}")
                    else:
                        # Handle sequence files with ####
                        if '####' in base_filename or base_filename.lower().endswith('.png'):
                            # Generate the frame number based on the job's frame list
                            frame_range = job.JobFramesList  # Assuming this is a list of frame numbers
                            # Generate the full list of filenames
                            filenames = [os.path.join(base_path, base_filename.replace('####', f"{frame:04d}")) for frame in frame_range]

                            # Check if the first movie file exists
                            still_path = filenames[0] if filenames else None
                            if still_path and os.path.exists(still_path):
                                self.LogInfo("Uploading still frame: " + still_path)
                                AutoShotgunUtils.UploadMovieToVersion(int(versionId), still_path, shotgunPath)
                            else:
                                self.LogInfo(f"ERROR: still file is missing: {still_path if still_path else 'No valid still files found.'}")
                else:
                    return
            else:
                return
        except Exception as e:
            ClientUtils.LogText(traceback.format_exc())
