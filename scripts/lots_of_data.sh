#!/bin/sh

# these lines ensure that any errors immediately kill the script and all children
set -e
trap "exit" INT TERM
trap "kill 0" EXIT

# get the url from the command line parameters
url="$1"
if [ -z "$url" ]; then
    echo "ERROR: you must enter a database url to connect to for the test"
    fail
fi

# run random_transfers in parallel
pids=''
for i in $(seq 1 100); do
    echo "iteration $i"
    python3 scripts/random_transfers.py $url --num_transfers=10000 &
    pids="$pids $!"
done

# wait on all of the runs to finish
wait
echo 'done'
