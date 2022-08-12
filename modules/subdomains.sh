#!/bin/bash
# https://github.com/gokulapap/submax
# subdomain enumeration

url=$1

/app/modules/binaries/subfinder -silent -d $url > /app/sub1
curl -s "https://crt.sh/?q=$url" | grep "<TD>" | grep $url | cut -d ">" -f2 | cut -d "<" -f1 | sort -u | sed '/^*/d' > /app/sub2
curl -s "https://riddler.io/search/exportcsv?q=pld:$url" | grep -Po "(([\w.-]*)\.([\w]*)\.([A-z]))\w+" | sort -u > /app/sub3
curl -s "https://jldc.me/anubis/subdomains/$url" | grep -Po "((http|https):\/\/)?(([\w.-]*)\.([\w]*)\.([A-z]))\w+" | cut -d "/" -f3 > /app/sub4
curl -s "https://dns.bufferover.run/dns?q=.$url" | jq -r .FDNS_A[] | cut -d',' -f2 | sort -u > /app/sub5
curl -s "https://certspotter.com/api/v1/issuances?domain=$url&include_subdomains=true&expand=dns_names" | jq .[].dns_names | grep -Po "(([\w.-]*)\.([\w]*)\.([A-z]))\w+" | sort -u > /app/sub6
curl -s "http://web.archive.org/cdx/search/cdx?url=*.$url/*&output=text&fl=original&collapse=urlkey" | sed -e 's_https*://__' -e "s/\/.*//" | sort -u > /app/sub7
curl -s "https://api.hackertarget.com/hostsearch/?q=$url" | sort -u > /app/sub8
curl -s "https://www.threatcrowd.org/searchApi/v2/domain/report/?domain=$url" | jq -r '.subdomains' | grep -o "\w.*$url" |sort -u > /app/sub9
curl -s "https://api.threatminer.org/v2/domain.php?q=$url&rt=5" | jq -r '.results[]' |grep -o "\w.*$url" | sort -u > /app/sub10

echo "7) SUBDOMAINS" >> /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

sort /app/sub1 /app/sub2 /app/sub3 /app/sub4 /app/sub5 /app/sub6 /app/sub7 /app/sub8 /app/sub9 /app/sub10 | uniq | tee /app/$url-subs
sort /app/sub1 /app/sub2 /app/sub3 /app/sub4 /app/sub5 /app/sub6 /app/sub7 /app/sub8 /app/sub9 /app/sub10 | uniq | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
