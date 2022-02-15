#!/bin/bash

#js_finder + link_finder

url=$1
furl=http://$url

furl=$(python3 -c "import requests; t = requests.head('$furl', allow_redirects=True).url; print(t)")

echo "9) JS FINDER + LINK FINDER" >> /app/results/${url}-output.txt
printf "\n\n" >> /app/results/${url}-output.txt

printf "JS FINDER :\n\n" >> /app/results/${url}-output.txt
/app/modules/binaries/gospider -s $furl -t 30 -d 1 | grep "\[javascript" | tee -a /app/results/${url}-output.txt
printf "\n\nLINK FINDER :\n\n" >> /app/results/${url}-output.txt
/app/modules/binaries/gospider -s $furl -t 30 | grep "\[linkfinder" | tee -a /app/results/${url}-output.txt


printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
