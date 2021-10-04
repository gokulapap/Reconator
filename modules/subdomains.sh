#!/bin/bash
# https://github.com/gokulapap/submax

url=$1

/app/modules/binaries/subfinder -silent -d $url > /app/sub1
curl -s "https://crt.sh/?q=$url" | grep "<TD>" | grep $url | cut -d ">" -f2 | cut -d "<" -f1 | sort -u | sed '/^*/d' > /app/sub2
curl -s "https://riddler.io/search/exportcsv?q=pld:$url" | grep -Po "(([\w.-]*)\.([\w]*)\.([A-z]))\w+" | sort -u > /app/sub3
curl -s "https://jldc.me/anubis/subdomains/$url" | grep -Po "((http|https):\/\/)?(([\w.-]*)\.([\w]*)\.([A-z]))\w+" | cut -d "/" -f3 > /app/sub4


echo "2) SUBDOMAINS :" >> /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

sort /app/sub1 /app/sub2 /app/sub3 /app/sub4 | uniq | tee /app/subs
sort /app/sub1 /app/sub2 /app/sub3 /app/sub4 | uniq | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "######################################################################" >> /app/results/$url-output.txt
printf "######################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
