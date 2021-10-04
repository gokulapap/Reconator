#!/bin/bash

url=$1

echo "1) DNSCAN :" | tee -a /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

printf "*NS RECORD*" >> /app/results/$url-output.txt
host -t ns $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*MX RECORD*" >> /app/results/$url-output.txt
host -t mx $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*SOA RECORD*" >> /app/results/$url-output.txt
host -t soa $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*DNSKEY*" >> /app/results/$url-output.txt
host -t dnskey $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*AAAA RECORD*" >> /app/results/$url-output.txt
host -t aaaa $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*CNAME RECORD*" >> /app/results/$url-output.txt
host -t cname $url | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "######################################################################" >> /app/results/$url-output.txt
printf "######################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
