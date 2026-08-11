import os
import time
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)

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
    
    await msg.edit(content=f'pong! (gateway: {gateway}ms) (rest: {rest}ms)')

bot.run(os.environ['TOKEN'])
