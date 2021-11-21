#!/bin/bash

#directory fuzzing

url=$1
furl=http://$url

furl=$(python3 -c "import requests; t = requests.head('$furl', allow_redirects=True).url; print(t)")

echo "8) DIRECTORY BRUTE" >> /app/results/${url}-output.txt
printf "\n\n" >> /app/results/${url}-output.txt

/app/modules/binaries/gobuster dir -q -w /app/modules/wordlists/common.txt -t 70 -u $furl | cut -d "[" -f1 | tee -a /app/results/${url}-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
