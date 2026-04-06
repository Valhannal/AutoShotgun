from __future__ import absolute_import, print_function
import sys
import os
import re
import json

import six
from six.moves import range

try:
    from typing import Any, Dict, List, Optional, Text, Tuple, Union
except ImportError:
    pass

from Deadline.Applications import DeadlineApplicationManager
from Deadline.Plugins import PluginConfig
from Deadline.Scripting import RepositoryUtils, FrameUtils, ClientUtils

import shotgun_api3.shotgun
from shotgun_api3.shotgun import Shotgun

sgObject = None

def ReplacePadding( inputFilename, framePaddingCharacter ):
    # type: (str, str) -> str
    """Replaces the padding to framePaddingCharacter (framePaddingCharacter can also be of type %0#d)"""
    # Error check input
    if framePaddingCharacter == "":
        framePaddingCharacter = "#"

    # Find the last occurence of the padding character after the directory separator
    filenameStart = max( inputFilename.rfind( '/' ), inputFilename.rfind( '\\' ) ) + 1
    firstOccurence = max( inputFilename.rfind( '#', filenameStart ), inputFilename.rfind( '?', filenameStart ) )

    # No padding characters found?
    if firstOccurence == -1:
        return inputFilename

    # We split the string into 3 parts, padding being the last occurence of #/? runs.
    paddingChar = inputFilename[firstOccurence]
    lastOccurence = 0
    for i in range( firstOccurence - 1, -1, -1 ):
        if( inputFilename[i] != paddingChar ):
            lastOccurence = i + 1
            break

    filenameA = inputFilename[0:lastOccurence]
    padding = inputFilename[lastOccurence:firstOccurence+1]
    filenameB = inputFilename[firstOccurence+1:]

    # Replace padding
    if framePaddingCharacter == "%0#d":
        padding = "%0" + str( len( padding ) ) + "d"
    elif re.match( "%0(\d)+d", framePaddingCharacter ) is not None:
        padding = framePaddingCharacter
    else:
        padding = padding.replace( paddingChar, framePaddingCharacter )

    outputPath = filenameA + padding + filenameB 

    return outputPath
    
def GetShotgun( shotgunPath=None, username=None, password=None ):
    # type: (Optional[Any], Optional[Any], Optional[Any]) -> Shotgun
    global sgObject
    # Return the cached instance if it exists
    if sgObject is not None:
        return sgObject

    if shotgunPath is None:
        shotgunPath = os.path.dirname( sys.argv[0] )

    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )

    url = six.ensure_str(SafeEncode( config.GetConfigEntry( 'ShotgunURL' ) ))
    proxy = six.ensure_str(SafeEncode( config.GetConfigEntry( 'ShotgunProxy' ) )) # type: Optional[bytes]
    if proxy == b"":
        proxy = None

    if LoginInfo.LoginByUser:
        print("Logging into Shotgrid as user with username: " + str(username))
        sgObject = GetShotgunForUserLogin( url, proxy, username, password)
    else:
        print("Logging into Shotgrid not as a user")
        #sgObject = GetShotgunForEventPlugin( url, proxy, config )
        name = SafeEncode(config.GetConfigEntry('ShotgunScriptName'))
        key = SafeEncode(config.GetConfigEntry('ShotgunScriptKey'))
        sgObject = shotgun_api3.shotgun.Shotgun(url, SafeDecode(name), SafeDecode(key), True, proxy, connect=False)

    try:
        noSslValidationString = config.GetConfigEntry( 'ShotgunNoSslValidation' ).lower()
        noSslValidation = ( noSslValidationString == "1" or noSslValidationString == "true" )
        sgObject.config.no_ssl_validation = noSslValidation
    except:
        pass
    LoginInfo.ShotgunInstance = sgObject
    return sgObject

def GetShotgunForEventPlugin( url, proxy, config ):
    # type: (str, Optional[bytes], PluginConfig) -> Shotgun
    if LoginInfo.ShotgunInstance:
        return LoginInfo.ShotgunInstance

    name = SafeEncode( config.GetConfigEntry( 'ShotgunScriptName' ) )

    dataController = DeadlineApplicationManager.GetBaseInstance().DataController
    secretsManagementEnabled = dataController.SecretsManagementEnabled
    if secretsManagementEnabled:
        key = SafeEncode( dataController.SecretsManagementController.GetSecret('/events/Shotgun/ShotgunScriptKey') )
    else:
        key = SafeEncode( config.GetConfigEntry( 'ShotgunScriptKey' ) )

    if proxy == b"":
        proxy = None

    sgObject = shotgun_api3.shotgun.Shotgun( url, SafeDecode(name), SafeDecode(key), True, proxy, connect=False )
    LoginInfo.Debug( "Connected to Shotgun using API key" )
    return sgObject

def GetShotgunForUserLogin( url, proxy, username=None, password=None ):
    # type: (str, Optional[bytes], Optional[Any], Optional[Any]) -> Shotgun
    if LoginInfo.ShotgunInstance and LoginInfo.SessionToken:
        return LoginInfo.ShotgunInstance

    if LoginInfo.SessionToken:
        sgObject = shotgun_api3.shotgun.Shotgun( session_token=LoginInfo.SessionToken, base_url=url,
                                                 convert_datetimes_to_utc=True, http_proxy=proxy, connect=False )
        LoginInfo.Debug( "Connected to Shotgun using session token=" + LoginInfo.SessionToken)
    else:
        sgObject = shotgun_api3.shotgun.Shotgun( login=username, password=password, base_url=url,
                                                 convert_datetimes_to_utc=True, http_proxy=proxy, connect=False )
        LoginInfo.SessionToken = sgObject.get_session_token()
        LoginInfo.WriteSessionToken( LoginInfo.SessionToken )
        LoginInfo.Debug( "Connected to Shotgun using username/password. Got session_token=" + LoginInfo.SessionToken )

    return sgObject

# Utility function to safely try to encode strings (or dict/list contents)    
def SafeEncode( obj, useEncoding='utf-8' ):
    # type: (Any, str) -> Any
    """return type will actually be something like:
    
    Union[bytes, List[bytes], Dict[Any, bytes]]

    but mypy makes this really messy to handle at each usage."""
    try:
        if isinstance( obj, six.text_type ):
            #it's unicode, encode it
            return obj.encode( useEncoding )
        elif isinstance( obj, bytes ):
            #already a str, just return it
            return obj
        elif isinstance( obj, dict ):
            #recursively convert contents
            for k, v in six.iteritems(obj):
                obj[k] = SafeEncode( v )
        elif isinstance( obj, list ):
            #recursively convert contents
            for i in range( len(obj) ):
                obj[i] = SafeEncode( obj[i] )
        else:
            #last ditch attempt
            return six.ensure_binary(obj, encoding=useEncoding)
    except:
        pass

    return obj
    
# Utility function to safely try to decode strings (or dict/list contents)
def SafeDecode( obj, useEncoding='utf-8' ):
    # type: (Any, str) -> Any
    """return type will actually be something like:
    
    Union[Text, List[Text], Dict[Any, Text]]

    but mypy makes this really messy to handle at each usage."""
    try:
        if isinstance( obj, six.text_type ):
            #already unicode, just return it
            return obj
        elif isinstance( obj, bytes ):
            #it's a str, decode it
            return obj.decode( useEncoding )
        elif isinstance( obj, dict ):
            #recursively convert contents
            for k, v in six.iteritems(obj):
                obj[k] = SafeDecode( v )
        elif isinstance( obj, list ):
            #recursively convert contents
            for i in range( len(obj) ):
                obj[i] = SafeDecode( obj[i] )
        else:
            #last ditch attempt
            return six.text_type( obj, encoding=useEncoding )
    except:
        pass

    return obj
    
    
def GetShotgunAPIVersion():
    # type: () -> str
    if hasattr( shotgun_api3.shotgun, '__version__' ):
        return shotgun_api3.shotgun.__version__
    else:
        return ""

def GetUserNames( shotgunPath=None ):
    # type: (Optional[Any]) -> List[str]
    userNames = []
    
    sg = GetShotgun( shotgunPath )
    users = sg.find("HumanUser",filters=[], fields=['login'], order=[{'field_name':'login','direction':'asc'}])
    for user in users:
        userNames.append( user['login'] )
        print(user)
    userNames.sort()
    
    return SafeDecode( userNames )
    
def GetUser( loginName, shotgunPath=None, password=None ):
    # type: (str, Optional[Any], Optional[str]) -> Optional[Dict[str, Any]]
    try:
        sg = GetShotgun( shotgunPath, loginName, password )

        user = sg.find_one("HumanUser", filters=[["login","is",loginName]], fields=['login','name'])
        return SafeDecode( user )
    except:
        # This is for session token failure or login failure
        LoginInfo.SessionToken = None
        raise

def GetProjects( shotgunPath=None ):
    # type: (Optional[Any]) -> List[Dict[str, Any]]
    sg = GetShotgun( shotgunPath )
    projects = []
    projects = sg.find('Project', filters=[['sg_status', 'is_not', 'Archive'],['name', 'is_not', 'Template Project']], fields=['name'], order=[{'field_name':'name','direction':'asc'}])
    return SafeDecode( projects )

def GetShotsAndAssets( projectID, shotgunPath=None ):
    # type: (int, Optional[Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
    sg = GetShotgun( shotgunPath )
    project = {'type' : 'Project', 'id' : projectID}
    assets = []
    assets = sg.find('Asset',
                 filters=[['project', 'is', project]],
                 fields=['code'],
                 order=[{'field_name':'code','direction':'asc'}])
    shots = []
    shots = sg.find('Shot',
                filters=[['project', 'is', project]],
                fields=['code','sg_sequence'],
                order=[{'field_name':'sequence','direction':'asc'},{'field_name':'name','direction':'asc'}])
    return SafeDecode( shots ), SafeDecode( assets)

def GetShotsAssetsAndElements( projectID, shotgunPath=None ):
    # type: (int, Optional[Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]
    shots, assets = GetShotsAndAssets( projectID, shotgunPath )
    
    sg = GetShotgun( shotgunPath )
    project = { 'type' :'Project', 'id' : projectID }
    elements = []
    
    #This blows up if Elements aren't turned on
    if 'Element' in sg.schema_entity_read():
        elements = sg.find('Element',
                       filters=[['project', 'is', project]],
                       fields=['code'],
                       order=[{'field_name':'code','direction':'asc'}])
    
    return SafeDecode( shots ), SafeDecode( assets ), SafeDecode( elements )

def GetTasks( userName, draftField = None, shotgunPath=None ):
    # type: (str, Optional[str], Optional[Any]) -> List[Dict[str, Any]]
    tasks = []
    return_fields = ['content','project','entity','step']

    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )
    statusListStr = config.GetConfigEntry(  "ShotgunStatusList" )
    
    if statusListStr == "":
        return []
    
    statusList = statusListStr.replace( " ", "" ).split( "," )
    
    if draftField is None:
        draftField = config.GetConfigEntry( 'DraftTemplateField' )
    
    #The Shotgun API doesn't like blank fields anymore, so check for that before tossing it in
    if draftField is not None and draftField.strip() != "":
        return_fields.append( draftField )
    
    sg = GetShotgun( shotgunPath )
    
    userEntry = sg.find_one("HumanUser",filters=[["login","is",userName]],fields=['login','name'])
    if userEntry:
        tasks = sg.find("Task", filters=[['sg_status_list', 'in', statusList],["task_assignees", "is", userEntry]], fields=return_fields, order=[{'field_name':'project','direction':'asc'},{'field_name':'entity','direction':'asc'},{'field_name':'content','direction':'asc'},{'field_name':'step','direction':'asc'}])
        
        #This is a more comprehensive task filter.  Will return everything all tasks that are not 'Final' or 'Complete'
        #tasks = sg.find("Task", filters=[['sg_status_list', 'is_not', 'fin'],['sg_status_list', 'is_not', 'cmpt'],["task_assignees", "is", userEntry]], fields=['content','project','entity',draftField])
        
        #standardize where the draft template is stashed, so we don't have to look it up all the time
        for task in tasks:
            task["draftTemplate"] = task.get( draftField, "" )
    
    return SafeDecode( tasks )

def GetVersions( entityType, entityID, shotgunPath=None ):
    # type: (str, int, Optional[Any]) -> List[Dict[str, Any]]
    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )

    pathField = config.GetConfigEntry( 'VersionEntityPathToFramesField' )
    firstFrameField = config.GetConfigEntry( 'VersionEntityFirstFrameField' )
    lastFrameField = config.GetConfigEntry( 'VersionEntityLastFrameField' )
    
    versions = []
    
    sg = GetShotgun( shotgunPath )
    entity = { 'type' : entityType, 'id' : entityID }
    versions = sg.find("Version",[['entity', 'is', entity]],['code', pathField, firstFrameField, lastFrameField, 'description'])
    return SafeDecode( versions )

def GetVersion( versionID, shotgunPath=None ):
    # type: (int, Optional[Any]) -> Dict[str, Any]
    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )

    pathField = config.GetConfigEntry( 'VersionEntityPathToFramesField' )
    firstFrameField = config.GetConfigEntry( 'VersionEntityFirstFrameField' )
    lastFrameField = config.GetConfigEntry( 'VersionEntityLastFrameField' )
    jobIDField = config.GetConfigEntryWithDefault('VersionEntityJobIDField', '')
    draftField = config.GetConfigEntryWithDefault('DraftTemplateField', '')

    fieldFilter = ['code','id','project','entity','user',pathField,firstFrameField,lastFrameField,'description']
    if jobIDField != '':
        fieldFilter.append( jobIDField )

    if draftField:
        fieldFilter.append( 'sg_task.Task.' + draftField )
    
    sg = GetShotgun( shotgunPath )
    version = sg.find_one('Version', [['id','is',versionID]], fieldFilter)
    if version and version['user'] and ('name' in version['user']):
        user = sg.find_one('HumanUser',[['name','is',version['user']['name']]],['login'])
        version['user']['login'] = user['login']
    return SafeDecode( version )
    
def AddNewVersion( userName, taskId, projectId, entityId, entityType, version, description, frameList, frameCount, outputPath, shotgunPath=None, jobID="" ):
    # type: (str, Optional[int], int, int, str, str, str, str, int, str, Optional[Any], str) -> Dict[str, Any]
    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )

    sg = GetShotgun( shotgunPath )
    print("Shotgrid username is:" + str(userName))
    user = sg.find_one("HumanUser",filters=[["login","is",userName]],fields=['login','name'])
    
    startFrame = -1
    endFrame = -1
    
    frames = FrameUtils.Parse( str(frameList) )
    startFrame = frames[ 0 ]
    endFrame = frames[ -1 ]
    
    data = { 
        'user': user,
        'code': version,
        'description': description,
        'created_by': user,
        'sg_status_list': 'na'  # Added status 'na' (N/A)
        }
        
    if config.GetConfigEntryWithDefault('VersionEntityPathToFramesField', "") != "":
        data[ config.GetConfigEntry( 'VersionEntityPathToFramesField' ) ] = outputPath
    
    if config.GetConfigEntryWithDefault('VersionEntityFrameRangeField', "") != "":
        data[ config.GetConfigEntry( 'VersionEntityFrameRangeField' ) ] = frameList
    
    if config.GetConfigEntryWithDefault('VersionEntityFrameCountField', "") != "":
        data[ config.GetConfigEntry( 'VersionEntityFrameCountField' ) ] = frameCount
    
    if config.GetConfigEntryWithDefault('VersionEntityFirstFrameField', "") != "":
        data[ config.GetConfigEntry( 'VersionEntityFirstFrameField' ) ] = int(startFrame)
    
    if config.GetConfigEntryWithDefault('VersionEntityLastFrameField', "") != "":
        data[ config.GetConfigEntry( 'VersionEntityLastFrameField' ) ] = int(endFrame)
    
    if config.GetConfigEntryWithDefault('VersionEntityJobIDField', "") != "":
        data[ config.GetConfigEntry( 'VersionEntityJobIDField' ) ] = jobID

    if taskId is not None and config.GetConfigEntryWithDefault('VersionEntityTaskField',"") != "":
        data[config.GetConfigEntry('VersionEntityTaskField')] = {'type': 'Task', 'id': taskId}
        task = sg.find_one('Task', [['id', 'is', taskId]], ['entity', 'project'])
        if task:
            data['project'] = task['project']
            data['entity'] = task['entity']
        else:
            raise ValueError(f"Task with ID {taskId} not found.")
    else:
        data['project'] = {'type':'Project', 'id':projectId}
        data['entity'] = {'type':entityType, 'id':entityId}
    
    new_version = sg.create('Version', data)
    
    return SafeDecode( new_version )

def AddNewVersionNoTask( userName, projectId, entityId, entityType, version, description, frameList, frameCount,outputPath, shotgunPath=None, jobID=""):
    # type: (str, int, int, str, str, str, str, int, str, Optional[Any], str) -> Dict[str, Any]
    config = RepositoryUtils.GetEventPluginConfig('Shotgun')
    sg = GetShotgun(shotgunPath)
    print("Shotgrid username is:" + str(userName))
    user = sg.find_one("HumanUser", filters=[["login", "is", userName]], fields=['login', 'name'])
    startFrame = -1
    endFrame = -1

    frames = FrameUtils.Parse(str(frameList))
    startFrame = frames[0]
    endFrame = frames[-1]
    data = {
        'user': user,
        'code': version,
        'description': description,
        'created_by': user,
        'sg_status_list': 'na'
    }

    if config.GetConfigEntryWithDefault('VersionEntityPathToFramesField', "") != "":
        data[config.GetConfigEntry('VersionEntityPathToFramesField')] = outputPath

    if config.GetConfigEntryWithDefault('VersionEntityFrameRangeField', "") != "":
        data[config.GetConfigEntry('VersionEntityFrameRangeField')] = frameList

    if config.GetConfigEntryWithDefault('VersionEntityFrameCountField', "") != "":
        data[config.GetConfigEntry('VersionEntityFrameCountField')] = frameCount

    if config.GetConfigEntryWithDefault('VersionEntityFirstFrameField', "") != "":
        data[config.GetConfigEntry('VersionEntityFirstFrameField')] = int(startFrame)

    if config.GetConfigEntryWithDefault('VersionEntityLastFrameField', "") != "":
        data[config.GetConfigEntry('VersionEntityLastFrameField')] = int(endFrame)

    if config.GetConfigEntryWithDefault('VersionEntityJobIDField', "") != "":
        data[config.GetConfigEntry('VersionEntityJobIDField')] = jobID

    data['project'] = {'type': 'Project', 'id': projectId}
    data['entity'] = {'type': entityType, 'id': entityId}

    new_version = sg.create('Version', data)
    return SafeDecode( new_version )

def UpdateVersion( versionId, statusCode, shotgunPath=None ):
    # type: (int, str, Optional[Any]) -> None
    sg = GetShotgun( shotgunPath )
    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )
    data = { config.GetConfigEntry( 'VersionEntityStatusField' ) : statusCode}
    sg.update('Version', versionId, data)

def UpdateRenderTimeForVersion( versionID, avgRenderTime, totalRenderTime, shotgunPath=None ):
    # type: (int, str, str, Optional[Any]) -> None
    sg = GetShotgun( shotgunPath )
    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )

    data = {}
    
    #append the relevant fields to the data dictionary
    avgTimeFieldName = config.GetConfigEntry( 'VersionEntityAverageTimeField' )
    if ( avgRenderTime is not None and avgTimeFieldName is not None and avgTimeFieldName.strip() != "" ):
        data.update( { avgTimeFieldName : avgRenderTime } )
    
    totalTimeFieldName = config.GetConfigEntry( 'VersionEntityTotalTimeField' )
    if ( totalRenderTime is not None and totalTimeFieldName is not None and totalTimeFieldName.strip() != "" ):
        data.update( { totalTimeFieldName : totalRenderTime } )
    
    #only upload if the fields are actually mapped
    if data:
        sg.update( 'Version', versionID, data )

def UploadMovieToVersion( versionID, path, shotgunPath=None ):
    # type: (int, str, Optional[Any]) -> None
    sg = GetShotgun( shotgunPath )
    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )

    pathToMovieField = config.GetConfigEntry( 'VersionEntityPathToMovieField' )
    if ( pathToMovieField is not None and pathToMovieField.strip() != "" ):
        data = { pathToMovieField : path }
        sg.update( 'Version', versionID, data )
    
    sg.upload( 'Version', versionID, path, config.GetConfigEntry( 'VersionEntityUploadMovieField' ) )

def UploadFilmstripToVersion( versionID, path, shotgunPath=None ):
    # type: (int, str, Optional[Any]) -> None
    sg = GetShotgun( shotgunPath )
    sg.upload_filmstrip_thumbnail( 'Version', versionID, path )
    
def UploadThumbnailToVersion( versionID, path, shotgunPath=None ) :
    # type: (int, str, Optional[Any]) -> None
    sg = GetShotgun( shotgunPath )
    sg.upload_thumbnail( 'Version', versionID, path )
    
def CreateActionMenuItem ( title, entity, shotgunPath=None ) :
    # type: (str, str, Optional[Any]) -> None
    sg = GetShotgun( shotgunPath )
    data = {
      "title":title,
      "url": "draft://submit_job_to_deadline",
      "list_order": 1,
      "entity_type": entity,
      "selection_required": True, 
    }
    if ( sg.find_one('ActionMenuItem', [['title', 'is', title]]) is None ) :
        sg.create('ActionMenuItem', data)

class LoginInfo:
    """
    We use LoginInfo as a static class to store login information.
    SessionToken is used to store the session token once Shotgun is connected successfully.
    LoginByUser indicates whether the current user is a client-side user or a event plugin. Client-side users are forced
    to use local credential, either username/password or session token.
    ShotgunInstance is the Shotgun object to be used to get information from Shotgun. It is for reuse so we do not have
    to connect to Shotgun every time.
    """
    # Warning: LogForDebug must never be True in production. Secrets may leak to the log if it is enabled.
    LogForDebug = False
    TempFileName = os.path.join( ClientUtils.GetUsersSettingsDirectory(), "ShotgunSession.json" )
    SessionToken = None
    LoginByUser = False
    ShotgunInstance = None

    @staticmethod
    def Debug( log ):
        # type: (str) -> None
        if LoginInfo.LogForDebug:
            print( log )

    @staticmethod
    def LoadSessionToken():
        # type: () -> None
        try:
            LoginInfo.LoginByUser = True
            with open( LoginInfo.TempFileName, "r" ) as fileHandle:
                shotgunLoginInfo = json.loads( fileHandle.read() )
                LoginInfo.SessionToken = shotgunLoginInfo.get( "session_token" )
                LoginInfo.Debug( "Loaded Shotgun session_token=" + LoginInfo.SessionToken )
        except:
            LoginInfo.SessionToken = None

    @staticmethod
    def WriteSessionToken( sessionToken ):
        # type: (str) -> None
        shotgunLoginInfo = { "session_token" : sessionToken }

        try:
            with open( LoginInfo.TempFileName, "w" ) as fileHandle:
                fileHandle.write( json.dumps( shotgunLoginInfo ) )
                LoginInfo.Debug( "Saved Shotgun session_token=%s to %s" % (LoginInfo.SessionToken, LoginInfo.TempFileName) )
        except:
            error = "Failed to save session token to file " + LoginInfo.TempFileName
            print( error )
            raise Exception( error )
    
########################################################################
## This handles the case where the script is called from the command line.
########################################################################
if hasattr( sys, 'argv' ) and len( sys.argv ) > 1:
    config = RepositoryUtils.GetEventPluginConfig( 'Shotgun' )
    arg = sys.argv[1]

    # Since this is probably only a command line tool for testing purpose for developers,
    # we force it to be a client-side user to use local credential
    LoginInfo.LoadSessionToken()

    if arg == "Login" and len(sys.argv) > 3:
        GetShotgun( None, username=sys.argv[2], password=sys.argv[3] )

    if arg == "CreateActionMenuItem" and len(sys.argv) > 3:
        CreateActionMenuItem(sys.argv[2], sys.argv[3])
    
    if arg == "Users":
        userNames = GetUserNames()
        for userName in userNames:
            print( "%s" % userName )
    
    if arg == "Projects":
        projects = GetProjects()
        for project in projects:
            print( "ProjectName=%s" % project['name'] )
            print( "ProjectID=%s" % project['id'] )
            print( "" )
            
    if arg == "ShotsAndAssets" and len(sys.argv) > 2:
        projectID = int(sys.argv[2])
        shots,assets = GetShotsAndAssets(projectID)
        for shot in shots:
            print( "ShotCode=%s" % shot['code'] )
            print( "ShotID=%s" % shot['id'] )
            print( "" )
        for asset in assets:
            print( "AssetCode=%s" % asset['code'] )
            print( "AssetID=%s" % asset['id'] )
            print( "" )
            
    if arg == "Tasks" and len( sys.argv ) > 2:
        
        draftField = config.GetConfigEntry( 'DraftTemplateField' )
        
        userName = sys.argv[2]
        
        tasks = GetTasks( userName, draftField )
        for task in tasks:
            print( "TaskName=%s" % task['content'] )
            print( "TaskID=%s" % task['id'] )
            print( "DraftTemplate=%s" % task[draftField] )
            if task['project'] is not None:
                print( "ProjectName=%s" % task['project']['name'] )
                print( "ProjectID=%s" % task['project']['id'] )
            if task['entity'] is not None:
                print( "EntityName=%s" % task['entity']['name'] )
                print( "EntityType=%s" % task['entity']['type'] )
                print( "EntityID=%s" % task['entity']['id'] )
            print( "" )
    
    if arg == "Version" and len( sys.argv ) > 2:
    
        versionID = int(sys.argv[2])
        version = GetVersion( versionID )
        print( "VersionCode=%s" % version['code'] )
        print( "VersionUser=%s" % version['user']['login'] )
        print( "VersionProjectID=%s" % version['project']['id'] )
        print( "VersionEntityType=%s" % version['entity']['type'] )
        print( "VersionEntityID=%s" % version['entity']['id'] )
        print ("")
        
    if arg == "Versions" and len( sys.argv ) > 3:

        pathField = config.GetConfigEntry( 'VersionEntityPathToFramesField' )
        firstFrameField = config.GetConfigEntry( 'VersionEntityFirstFrameField' )
        lastFrameField = config.GetConfigEntry( 'VersionEntityLastFrameField' )
        
        entityType = sys.argv[2]
        entityID = int(sys.argv[3])
        
        versions = GetVersions( entityType, entityID )

        for version in versions:
            print( "VersionCode=%s" % version['code'] )
            print( "VersionID=%s" % version['id'] )
            if ( pathField in version ) :
                print( "VersionPath=%s" % version[pathField] )
            else :
                print( "VersionPath=" )
            if ( firstFrameField in version ) :
                print( "VersionFirstFrame=%s" % version[firstFrameField] )
            else :
                print( "VersionFirstFrame=" )
            if ( lastFrameField in version ) :
                print( "VersionLastFrame=%s" % version[lastFrameField] )
            else :
                print( "VersionLastFrame=" )
            print( "" )
            
    if arg == "NewVersion" and len( sys.argv ) > 11:
        userName = sys.argv[2]
        taskId = int(sys.argv[3])
        projectId = int(sys.argv[4])
        entityId = int(sys.argv[5])
        entityType = sys.argv[6]
        version_str = sys.argv[7]
        description = sys.argv[8]
        frameList = sys.argv[9]
        frameCount = int(sys.argv[10])
        outputPath = sys.argv[11]
        
        if taskId!=None:
            new_version = AddNewVersion( userName, taskId, projectId, entityId, entityType, version_str, description, frameList, frameCount, outputPath )
        else:
            new_version = AddNewVersionNoTask(userName, projectId, entityId, entityType, version_str, description,frameList, frameCount, outputPath)
        print( "New Shotgun version created with ID: %s" % new_version['id'] )
    
    if arg == "Update" and len( sys.argv ) > 3:
        versionId = int(sys.argv[2])
        statusCode = sys.argv[3]
        
        UpdateVersion( versionId, statusCode )

    if arg == "UpdateRenderTime" and len( sys.argv ) > 4:
        versionId = int(sys.argv[2])
        avgRenderTime = sys.argv[3]
        totalRenderTime = sys.argv[4]
        
        UpdateRenderTimeForVersion( versionId, avgRenderTime, totalRenderTime )

    if arg == "Upload" and len( sys.argv ) > 3:
        versionId = int(sys.argv[2])
        path = sys.argv[3]
        
        UploadMovieToVersion( versionId, path )
        
    if arg == "UploadThumbnail" and len( sys.argv ) > 3:
        versionId = int(sys.argv[2])
        path = sys.argv[3]

        UploadThumbnailToVersion( versionId, path )