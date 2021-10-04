#python run.py {domain}

import os
import sys
import telebot

url = sys.argv[1]
bot = telebot.TeleBot(os.environ['API_KEY'])
chat_id = os.environ['CHAT_ID']

os.system("touch results/{}-output.txt".format(url))
os.system("chmod 777 /app/* -R")

bot.send_message(chat_id, f"Recon started for {url} !")

#1_dnscan
os.system(f"bash modules/dnscan.sh {url}")

#2_clickjacking
os.system(f"modules/clickjacking {url}")

#3_subdomain_enumeration
os.system(f"bash modules/subdomains.sh {url}")

#4_dirbrute
os.system(f"bash modules/dirb.sh {url}")

#5_urls_gather
os.system(f"bash modules/gather_urls.sh {url}")

bot.send_message(chat_id, f"Recon for {url} is completed ! you can check the results now on website !")
#dumping to database with insert.py
os.system('python insert.py {}'.format(url))
