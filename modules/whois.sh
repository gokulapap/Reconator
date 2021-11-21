#!/bin/bash

url=$1

echo "13) WHOIS LOOKUP" >> /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

whois $url | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
