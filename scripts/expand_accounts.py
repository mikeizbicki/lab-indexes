#!/usr/bin/python3

import argparse
import random

if __name__ == '__main__':

    # process command line args
    parser = argparse.ArgumentParser()
    parser.add_argument('infile')
    parser.add_argument('--num_accounts', type=int, default=20000)
    args = parser.parse_args()

    # parse csv
    accounts = []
    with open(args.infile) as f:
        for i,line in enumerate(f):
            line = line.strip()
            name, description = line.split('\t')
            if i>0:
                accounts.append((name, description))
            print(line)

    # generate new accounts
    for i in range(args.num_accounts):
        account1 = random.choice(accounts)
        account2 = random.choice(accounts)
        name = ' '.join(account1[0].split()[:-1]) + ' ' + account2[0].split()[-1]
        choice = random.choice([1,2,3,4,5])
        if choice == 0:
            name = name.lower()
        elif choice == 1 or choice == 2:
            name = name.upper()
        description = account1[1].split('.')[0] + '. ' + account2[1].split('.')[1]
        print(f'{name}\t{description}')
