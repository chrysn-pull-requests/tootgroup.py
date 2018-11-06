#!/usr/bin/python3

## tootgroup.py
## Version 0.6
##
##
## Andreas Schreiner
## @andis@chaos.social
## andreas.schreiner@sonnenmulde.at
##
## License: General Public License Version 3
## See attached LICENSE file.
##

import argparse
import configparser
import html
import os
import re
import requests
import sys

from mastodon import Mastodon



# Execution starts here.
def main():

    # Get the user the script is running for.
    my_commandline_arguments = parse_arguments()
    
    # TODO: standard storage place for config (and tmp files?)
    # TODO: remove ramaining temp files from last run if the script did not close cleanly
    my_config_file = "tootgroup.conf"
    write_new_config = False
    my_group_name = my_commandline_arguments["group_name"]
    
    # Get and validate configuration from the config file.
    my_config = parse_configuration(my_config_file, my_group_name)
    
    # Create Mastodon API instance.
    mastodon = Mastodon(
        client_id = my_config[my_group_name]["client_id"],
        access_token = my_config[my_group_name]["access_token"],
        api_base_url = my_config[my_group_name]["mastodon_instance"]
    )
    
    try:
        # Get the group account and all corresponding information
        # name, id, group members (== accounts followed by the group)
        # their IDs and the time of the group's last toot.
        #
        # This connects to the Mastodon server for the first time - catch any
        # excpetions that may occur from that here.
        my_account = {
            "username": mastodon.account_verify_credentials().username, 
            "id": mastodon.account_verify_credentials().id, 
            "group_members": "", 
            "group_member_ids": [], 
            "last_toot_time":  ""
        }
    except Exception as e:
        print("")
        print(e)
        print("\n########################################################")
        print("tootgroup.py could not connect to the Mastodon server.")
        print("If you know that it is running, there might be a")
        print("problem with our local configuration.")
        print("\nDelete tootgroup.py's config file and re-run the script")
        print("for a new setup.")
        print("########################################################\n")
        sys.exit(0)
    # Extract account information that could not be fetched directly    
    my_account["group_members"] = mastodon.account_following(my_account["id"])
    for member in my_account["group_members"]:
        my_account["group_member_ids"].append(member.id)
    
    # Do we accept direct messages, public retoots, both or none? This
    # can be set in the configuration.
    accept_DMs = my_config[my_group_name].getboolean("accept_DMs")
    accept_retoots = my_config[my_group_name].getboolean("accept_retoots")
    
    # Get all new notifications up to a maximum number set here.
    # Defaults to 100 and has to be changed in the code if really desired.
    # Use the ID of the last toot or retoot for deciding what is new.
    notification_count = 0
    max_notifications = 100
    max_notification_id = None
    latest_notification_id = 0
    my_notifications = []
    get_more_notifications = True
    
    # TODO: check what happens if there are no or too few notifications yet
    #
    # Get notifications, stop if either the last known notification ID or
    # the maximum number is reached.
    while get_more_notifications:
        get_notifications = mastodon.notifications(max_id = max_notification_id)
        
        # remember the ID of the latest notification
        if notification_count == 0:
            latest_notification_id = get_notifications[0].id
        
        for notification in get_notifications:
            max_notification_id = notification.id
            
            if notification.id > int(my_config[my_group_name]["last_seen_id"]) and notification_count < max_notifications:
                my_notifications.append(notification)
            else:
                get_more_notifications = False
            
            notification_count += 1
    
    # If there have been new notifications since the last run, update "last_seen_id"
    # and update config file to persist the new value.
    if latest_notification_id > int(my_config[my_group_name]["last_seen_id"]):
        my_config[my_group_name]["last_seen_id"] = str(latest_notification_id)
        write_new_config = True
    
    
    # Reverse notification list so that the oldest notifications are processed first
    my_notifications = my_notifications[::-1]

    # run through the notifications and look for retoot candidates
    for notification in my_notifications:
        
        # Only from group members
        if notification.account.id in my_account["group_member_ids"]:
        
            # Is retooting of public mentions configured?
            if accept_retoots:
                if notification.type == "mention" and notification.status.visibility == "public":
                    # Only if the mention was preceeded by an "!". 
                    # To check this, html tags have to be removed first.
                    repost_trigger = "!@" + my_account["username"]
                    status = re.sub("<.*?>", "", notification.status.content)
                    if repost_trigger in status:
                        print("would now retoot ID: " + str(notification.status.id))
#                        mastodon.status_reblog(notification.status.id)
    
            # Is reposting of direct messages configured? - if yes then:
            # Look for direct messages
            if accept_DMs:
                if notification.type == "mention" and notification.status.visibility == "direct":
                    
                    # Remove HTML tags from the status content but keep linebreaks
                    new_status = re.sub("<br />", "\n", notification.status.content)
                    new_status = re.sub("</p><p>", "\n\n", new_status)
                    new_status = re.sub("<.*?>", "", new_status)
                    # Remove the @username from the text
                    rm_username = "@" + my_account["username"]
                    new_status = re.sub(rm_username, "", new_status)
                    # "un-escape" HTML special characters
                    new_status = html.unescape(new_status)
                    # Repost as a new status
                    print("would now repost new status: " + new_status)
#                    mastodon.status_post(
#                        new_status,
#                        media_ids = media_toot_again(notification.status.media_attachments, mastodon),
#                        sensitive = notification.status.sensitive,
#                        visibility = "public",
#                        spoiler_text = notification.status.spoiler_text
#                    )
    
    # There have been changes requiring to persist the new configuration
    if write_new_config:
        write_configuration(my_config_file, my_config)
    
    print("Successful tootgroup.py run for " + "@" + my_account["username"] +
        " at " + my_config[my_group_name]["mastodon_instance"])



def media_toot_again(orig_media_dict, mastodon_instance):
    """Re-upload media files to Mastodon for use in another toot.
    
    "orig_media_dict" - extracted media files from the original toot
    "mastodon_instance" - needed to upload the media files again and create
    a new media_dict.
    
    Mastodon does not allow the re-use of already uploaded media files (images,
    videos) in a new toot. This function downloads all media files from a toot
    and uploads them again.
    
    It returns a dict formatted in a proper way to be used by the 
    Mastodon.status_post() function."""
    new_media_dict = []
    for media in orig_media_dict:
        media_data = requests.get(media.url).content
        # TODO: temporary file maganement needed here
        filename = os.path.basename(media.url)
        # basename still includes a "?" followed by a number after the file's name. Remove them both.
        filename = filename.split("?")[0]
        with open(filename, "wb") as handler: # use "wb" instead of "w" to enable binary mode (needed on Windows)
            handler.write(media_data)
        new_media_dict.append(mastodon_instance.media_post(filename, description=media.description))
        os.remove(filename)
    return(new_media_dict)



def new_credentials_from_mastodon(group_name, config):
    """Register tootgroup.py at a Mastodon server and get user credentials.
    
    "group_name" points to the current groups settings in the config file
    "config" the configuration as read in from configparser
    
    This will be run if tootgroup.py is started for the first time, if its
    configuration files have been deleted or if some elements of the
    configuration are missing.
    TODO: catch login/register errors and retry
    """
    # Register tootgroup.py app at the Mastodon server
    try:
        Mastodon.create_app(
            "tootgroup.py",
            api_base_url = config[group_name]["mastodon_instance"],
            to_file = config[group_name]["client_id"]
        )
        # Create Mastodon API instance
        mastodon = Mastodon(
            client_id = config[group_name]["client_id"],
            api_base_url = config[group_name]["mastodon_instance"]
        )
    except Exception as e:
        print("")
        print(e)
        print("\n###################################################################")
        print("The Mastodon instance URL is wrong or the server does not respond.")
        print("tootgroup.py will exit now. Run it again to try once more!")
        print("###################################################################\n")
        sys.exit(0)
 
    # Log in once with username and password to get an access token for future logins.
    # Ask until login succeeds or at most 3 times before the skript gives up.
    i = 0
    while i < 3:
        i+=1
        try:
            mastodon.log_in(
                input("Username (e-Mail): "),
                input("Password: "),
                to_file = config[group_name]["access_token"]
            )
            break
        except Exception:
            print("\nUsername and/or Password did not match!")
            if i <3:
                print("Please enter them again.\n")
            else:
                print("tootgroup.py will exit now. Run it again to try once more!\n")
                sys.exit(0)



def parse_arguments():
    """Read arguments from the command line.
    
    parse_arguments() uses Python's agparser to read arguments from the command
    line. It also sets defaults and provides help and hints abouth which
    arguments are available
    
    Availble arguments:
    -u, --user: user the script is currently running for. Needed by configparser
    to find its configuration."""
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--user",  default="default", 
        help="Input username for the Mastodon group. tootgroup.py stores all "
        "information connected to a specific group account under this name. "
        "Choosing different names makes it then possible to manage multiple "
        "Mastodon groups at the same time. If no username is given, user "
        "\"%(default)s\" is always used instead.")
    args = parser.parse_args()    
    arguments = {}
    arguments["group_name"] = args.user
    return arguments



def parse_configuration(config_file,  group_name):
    """Read configuration from file, handle first-run situations and errors.
    
    "config_file" the path to the configuration file
    "group_name" determines the section to be read by configparser
    
    parse_configuration() uses Pyhon's configparser to read and interpret the
    config file. It will detect a missing config file or missing elements and
    then try to solve problems by asking the user for more information. This
    does also take care of a first run situation where nothing is set up yet and
    in that way act as an installer!
    
    parse_configuration should always return a complete and usable configuration"""
    config = configparser.ConfigParser()
    config.read(config_file)
    get_new_credentials = False
    write_new_config = False
    
    # Is there already a section for the current tootgroup.py
    # group. If not, create it now.
    if not config.has_section(group_name):
        config[group_name] = {}
        write_new_config = True
    
    # Do we have a mastodon instance URL? If not, we have to
    # ask for it and register with our group's server first.
    if not config.has_option(group_name,  "mastodon_instance"):
        config[group_name]["mastodon_instance"] = ""
    if config[group_name]["mastodon_instance"] == "":
        config[group_name]["mastodon_instance"] = input("Enter the "
            "URL of the Mastodon instance your group account is "
            "running on: ")
        get_new_credentials = True
        write_new_config = True
    
    # Where can the client ID be found and does the file exist?
    # If not, re-register the client.
    if not config.has_option(group_name,  "client_id"):
        config[group_name]["client_id"] = ""
    if config[group_name]["client_id"] == "":
        config[group_name]["client_id"] = group_name + "_clientcred.secret"
        get_new_credentials = True
        write_new_config = True
    if not os.path.isfile(config[group_name]["client_id"]):
        get_new_credentials = True
    
    # Where can the user access token be found and does the file exist?
    # If not, re-register the client to get new user credentials
    if not config.has_option(group_name,  "access_token"):
        config[group_name]["access_token"] = ""
    if config[group_name]["access_token"] == "":
        config[group_name]["access_token"] = group_name + "_usercred.secret"
        get_new_credentials = True
        write_new_config = True
    if not os.path.isfile(config[group_name]["access_token"]):
        get_new_credentials = True
    
    # Should tootgroup.py accept direct messages for reposting?
    if not config.has_option(group_name,  "accept_dms"):
        config[group_name]["accept_dms"] = ""
    if (config[group_name]["accept_dms"] == "") or (config[group_name]["accept_dms"] not in ("yes",  "no")):
        str = ""
        while True:
            str = input("\nShould tootgroup.py repost direct messages from group users? [yes/no]: ")
            if str.lower() not in ("yes",  "no"):
                print("Please enter 'yes' or 'no'!")
                continue
            else:
                break
        config[group_name]["accept_dms"] = str.lower()
        write_new_config = True
    
    # Should tootgroup.py accept public mentions for retooting?
    if not config.has_option(group_name,  "accept_retoots"):
        config[group_name]["accept_retoots"] = ""
    if (config[group_name]["accept_retoots"] == "") or (config[group_name]["accept_retoots"] not in ("yes",  "no")):
        str = ""
        while True:
            str = input("\nShould tootgroup.py retoot public mentions from group users? [yes/no]: ")
            if str.lower() not in ("yes",  "no"):
                print("Please enter 'yes' or 'no'!")
                continue
            else:
                break
        config[group_name]["accept_retoots"] = str.lower()
        write_new_config = True
    
    # The id of the last group-toot has to be persisted here. It is needed
    # to check for newly arrived notifications. Initialized with a sane value at setup.
    if (not config.has_option(group_name,  "last_seen_id")) or (config[group_name]["last_seen_id"] == ""):
        # TODO: v0.6 !! initialize last_seen_id with sane value
        config[group_name]["last_seen_id"] = "1"
        write_new_config = True    
    
    # Some registration info or credentials were missing - we have to register
    # tootgroup.py with our Mastodon server instance. (again?)
    if get_new_credentials:
        new_credentials_from_mastodon(group_name, config)
    
    # Have there been any changes to the configuration?
    # If yes we have to write them to the config file
    if write_new_config:
        write_configuration(config_file, config)
    
    # Configuration should be complete and working now - return it.
    return(config)


def write_configuration(config_file,  config):
    """Write out the configuration into the config file..
    
    "config_file" the path to the configuration file
    "config" configparser object containing the current configuration.
    
    This can be called whenever the configuration needs to be persisted by
    writing it to the disk."""
    with open(config_file, "w") as configfile:
            config.write(configfile)


# Start executing main() function if the script is called from a command line
if __name__=="__main__":
    main()
