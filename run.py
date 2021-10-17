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

#0_index_of_results
os.system(f"bash modules/index.sh {url}")

#1_dnscan
os.system(f"bash modules/dnscan.sh {url}")

#2_clickjacking
os.system(f"python modules/clickjacking {url}")

#3_corstest
os.system(f"python modules/corstest {url}")

#4_subdomain_enumeration
os.system(f"bash modules/subdomains.sh {url}")

#5_dirbrute
os.system(f"bash modules/dirb.sh {url}")

#6_firwall_detection
os.system(f"bash modules/firewall.sh {url}")

#7_urls_gather
os.system(f"bash modules/gather_urls.sh {url}")

###########################################################

bot.send_message(chat_id, f"Recon for {url} is completed ! you can check the results now on website at path /scanned !")
#dumping to database with insert.py
os.system('python insert.py {}'.format(url))
