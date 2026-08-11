import os
import time
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # важно для memberCount и событий входа/выхода
bot = commands.Bot(command_prefix='.', intents=intents)

WELCOME_CHANNEL_ID = 1536083742702043216

@bot.event
async def on_ready():
    print(f'Ботик {bot.user} проснулся! ❤️')

@bot.command(name='ping')
async def ping(ctx):
    start = time.time()
    msg = await ctx.send('Pong!')
    end = time.time()
    
    rest = round((end - start) * 1000)
    gateway = round(bot.latency * 1000)
    
    await msg.edit(content=f'Pong! (gateway: {gateway}ms) (rest: {rest}ms)')

@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        await channel.send(
            f'**к нам зашел новый участник! {member.mention}! получается, теперь нас {member.guild.member_count} *(включая ботов)*. ну шо сказать, классно!**'
        )

@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        await channel.send(
            f'**у нас вышел участник {member}, оч жаль(( но получается, нас теперь {member.guild.member_count} *(включая ботов),* что есть то есть!**'
        )

bot.run(os.environ['TOKEN'])
