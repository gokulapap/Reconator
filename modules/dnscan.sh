#!/bin/bash

url=$1

echo "1) DNSCAN :" | tee -a ../results/$url/output.txt
printf "\n\n" >> ../results/$url/output.txt

host -t ns $url | tee -a ../results/$url/output.txt
printf "\n" >> ../results/$url/output.txt
host -t mx $url | tee -a ../results/$url/output.txt
printf "\n" >> ../results/$url/output.txt
host -t soa $url | tee -a ../results/$url/output.txt
printf "\n" >> ../results/$url/output.txt
host -t dnskey $url | tee -a ../results/$url/output.txt
printf "\n" >> ../results/$url/output.txt
host -t aaaa $url | tee -a ../results/$url/output.txt
printf "\n" >> ../results/$url/output.txt
host -t cname $url | tee -a ../results/$url/output.txt

printf "\n\n" >> ../results/$url/output.txt
printf "############################################################" >> ../results/$url/output.txt
printf "\n\n" >> ../results/$url/output.txt
