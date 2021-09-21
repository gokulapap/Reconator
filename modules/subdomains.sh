#!/bin/bash
# https://github.com/gokulapap/submax

url=$1

/root/dev/reconator/modules/subfinder -d $url -silent > sub1

curl -s "https://crt.sh/?q=$url" | grep "<TD>" | grep $url | cut -d ">" -f2 | cut -d "<" -f1 | sort -u | sed '/^*/d' > sub3
curl -s "https://rapiddns.io/subdomain/$url#result" | grep "<td><a" | cut -d '"' -f 2 | grep http | cut -d '/' -f3 | sort -u > sub4
curl -s "https://dns.bufferover.run/dns?q=.$url" | jq -r .FDNS_A[] | cut -d '\' -f2 | cut -d "," -f2 |  sort -u > sub5
curl -s "https://riddler.io/search/exportcsv?q=pld:$url" | grep -Po "(([\w.-]*)\.([\w]*)\.([A-z]))\w+" | sort -u > sub6
curl -s "https://jldc.me/anubis/subdomains/$url" | grep -Po "((http|https):\/\/)?(([\w.-]*)\.([\w]*)\.([A-z]))\w+" | cut -d "/" -f3 > sub7
curl -s "https://sonar.omnisint.io/subdomains/$url" | cut -d "[" -f1 | cut -d "]" -f1 | cut -d "\"" -f 2 > sub8


echo "2) SUBDOMAINS :" >> ../results/$url/output.txt
printf "\n\n" >> results/$url/output.txt

sort sub1 sub2 sub3 sub4 sub5 sub6 sub7 sub8 | uniq | tee -a ../results/$url/output.txt
rm sub*

printf "\n\n" >> results/$url/output.txt
printf "############################################################" >> ../results/$url/output.txt
printf "\n\n" >> results/$url/output.txt

