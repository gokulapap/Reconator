#!/bin/bash

#dnscan

url=$1

echo "1) DNSCAN" | tee -a /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

printf "*NS RECORD*\n" >> /app/results/$url-output.txt
host -t ns $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*MX RECORD*\n" >> /app/results/$url-output.txt
host -t mx $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*SOA RECORD*\n" >> /app/results/$url-output.txt
host -t soa $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*DNSKEY*\n" >> /app/results/$url-output.txt
host -t dnskey $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*AAAA RECORD*\n" >> /app/results/$url-output.txt
host -t aaaa $url | tee -a /app/results/$url-output.txt
printf "\n" >> /app/results/$url-output.txt

printf "*CNAME RECORD*\n" >> /app/results/$url-output.txt
host -t cname $url | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
