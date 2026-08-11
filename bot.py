import os
import time
import discord
from discord.ext import commands

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    print(f'Ботик {bot.user} проснулся! ❤️')

@bot.command(name='ping')
async def ping(ctx):
    start = time.time()
    msg = await ctx.send('Понг! 🏓')
    end = time.time()
    
    latency = round((end - start) * 1000)
    ws_latency = round(bot.latency * 1000)
    
    await msg.edit(content=f'Понг! 🏓\nЗадержка сообщения: `{latency}ms`\nWebSocket: `{ws_latency}ms`')

bot.run(os.environ['TOKEN'])
