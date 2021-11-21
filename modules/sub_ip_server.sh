#!/bin/bash

url=$1

echo "12) SUBDOMAINS [IP + WEBSERVER]" >> /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

/app/modules/binaries/httpx -silent -no-color -threads 90 -ip -web-server -websocket -l /app/$url-subs | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
