""" Twitch plugin for twitch notifications.

More to come?

Commands:
    twitch
"""

import discord
import logging
from datetime import datetime, timedelta

from pcbot import utils, Config
import plugins
from plugins.twitchlib import twitch
client = plugins.client  # type: discord.Client


twitch_config = Config("twitch-config", data=dict(servers={}))

# Keep track of all {member.id: date} that are streaming
stream_history = {}
repeat_notification_delta = timedelta(hours=2)


async def on_reload(name):
    global stream_history
    local_history = stream_history

    await plugins.reload(name)

    stream_history = local_history


@plugins.command(name="twitch")
async def twitch_group(message: discord.Message, _: utils.placeholder):
    """ Administrative commands for twitch functions. Notifies when discord says you're streaming. """
    pass


@twitch_group.command(name="channels", permissions="manage_server")
async def notify_channels(message: discord.Message, *channels: discord.Channel):
    """ Specify channels to notify when a member goes live, or use no arguments to disable. """
    if message.server.id not in twitch_config.data["servers"]:
        twitch_config.data["servers"][message.server.id] = {}

    twitch_config.data["servers"][message.server.id]["notify_channels"] = [c.id for c in channels]
    twitch_config.save()

    # Tell the user if notifications were disabled
    assert channels, "**Disabled stream notifications in this server.**"

    await client.say(message, "**Notifying streams in:** {}".format(utils.format_objects(*channels, sep=" ")))


def make_twitch_embed(member: discord.Member, response: dict):
    """ Return an embed of the twitch stream, using the twitch api response.

    :param member: Member object streaming.
    :param response: Dict received through twitch.request("streams").
    """
    e = discord.Embed(title="Playing " + response["stream"]["game"], url=member.game.url,
                      description=member.game.name, color=member.color)
    e.set_author(name=member.display_name, url=member.game.url, icon_url=member.avatar_url)
    e.set_thumbnail(url=response["stream"]["preview"]["small"] + "?date=" + datetime.now().ctime().replace(" ", "%20"))
    return e


def started_streaming(before: discord.Member, after: discord.Member):
    """ Return True if the member just started streaming, and did not do so recently. """
    # The member is not streaming at the moment
    if after.game is None or not after.game.type == 1:
        return False

    # Check if they were also streaming before
    if before.game and before.game.type == 1:
        return False

    # Update the stream history
    previous_stream = stream_history.get(after.id)
    stream_history[after.id] = datetime.now()

    # Check that they didn't start streaming recently
    if previous_stream and datetime.now() < (previous_stream + repeat_notification_delta):
        return False

    return True


@plugins.event()
async def on_member_update(before: discord.Member, after: discord.Member):
    """ Notify given channels whenever a member goes live. """
    # Return if the server doesn't have any notify channels setup
    if not twitch_config.data["servers"].get(after.server.id, {}).get("notify_channels", False):
        return

    # Make sure the member just started streaming
    if not started_streaming(before, after):
        return

    # Tru getting the id and also log some possibly useful info during exceptions
    try:
        twitch_id = await twitch.get_id(after)
    except twitch.RequestFailed as e:  # Could not find the streamer due to a request error
        logging.info("Could not get twitch id of {}: {}".format(after, e))
        return
    except twitch.UserNotResolved as e:  # Ignore them if the id was not found.
        logging.debug(e)
        return

    # Return the stream info of the specified user
    try:
        stream_response = await twitch.request("streams/" + twitch_id)
    except twitch.RequestFailed as e:
        logging.info("Could not get twitch stream of {} (id: {}): {}".format(after, twitch_id, e))
        return

    # If the member isn't actually streaming, return (should not be the case as discord uses the twitch api too)
    if stream_response["stream"] is None:
        return

    # Create the embedded message and send it to every stream channel
    embed = make_twitch_embed(after, stream_response)
    for channel_id in twitch_config.data["servers"][after.server.id]["notify_channels"]:
        await client.send_message(after.server.get_channel(channel_id), embed=embed)
