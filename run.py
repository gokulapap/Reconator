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

#4_firwall_detection
os.system(f"bash modules/firewall.sh {url}")

#5_davtest
os.system(f"bash modules/davtest.sh {url}")

#6_robots_check
os.system(f"bash modules/robots.sh {url}")

#7_subdomain_enumeration
os.system(f"bash modules/subdomains.sh {url}")

#8_dirbrute
os.system(f"bash modules/dirb.sh {url}")

#9_js+link_finder
os.system(f"bash modules/js-finder.sh {url}")

#10_subdomain_takeover
os.system(f"bash modules/subtake.sh {url}")

#11_subdomains_title_cname
os.system(f"bash modules/sub_title_cname.sh {url}")

#12_subdomains_ip_server
os.system(f"bash modules/sub_ip_server.sh {url}")

#13_whois_lookup
os.system(f"bash modules/whois.sh {url}")

#14_shcheck
os.system(f"bash modules/shcheck.sh {url}")

#15_wappalyzer_cli
os.system(f"bash modules/wappy.sh {url}")

#16_urls_gather
os.system(f"bash modules/gather_urls.sh {url}")

#17_seperating_with_gf_patterns
os.system(f"bash modules/gf_patterns.sh {url}")

#18

###########################################################

bot.send_message(chat_id, f"Recon for {url} is completed ! you can check the results now on website at path /scanned !")
#dumping to database with insert.py
os.system('python insert.py {}'.format(url))
