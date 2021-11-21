#!/bin/bash

#webdav file upload test

url=$1

echo "5) WEBDAV FILE UPLOAD TEST" >> /app/results/${url}-output.txt
printf "\n\n" >> /app/results/${url}-output.txt

python /app/modules/binaries/davtest $url | tee -a /app/results/${url}-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
