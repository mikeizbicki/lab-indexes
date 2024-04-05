import sqlalchemy
from sqlalchemy.sql import text
import os
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format=f'%(asctime)s.%(msecs)03d - {os.getpid()} - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)


class Ledger:
    '''
    This class provides a python interface to the ledger database.
    Each method performs appropriate SQL commands to manipulate the database.
    '''

    def __init__(self, url):
        # create the database connection
        self.engine = sqlalchemy.create_engine(url)
        self.connection = self.engine.connect()

    def get_all_account_ids(self):
        sql = text('SELECT account_id FROM accounts;')
        logging.debug(sql)
        results = self.connection.execute(sql)
        return [row['account_id'] for row in results.all()]

    def create_account(self, name):
        with self.connection.begin():

            # insert the name into "accounts"
            sql = text('INSERT INTO accounts (name) VALUES (:name);')
            sql = sql.bindparams(name=name)
            logging.debug(sql)
            self.connection.execute(sql)

            # get the account_id for the new account
            sql = text('SELECT account_id FROM accounts WHERE name=:name')
            sql = sql.bindparams(name=name)
            logging.debug(sql)
            results = self.connection.execute(sql)
            account_id = results.first()['account_id']

            # add the row into the "balances" table
            sql = text('INSERT INTO balances VALUES (:account_id, 0);')
            sql = sql.bindparams(account_id=account_id)
            logging.debug(sql)
            self.connection.execute(sql)

    def transfer_funds(
            self,
            debit_account_id,
            credit_account_id,
            amount
            ):
        while True:
            try:
                return self._transfer_funds(debit_account_id, credit_account_id, amount)
            except sqlalchemy.exc.OperationalError as e:
                #pass
                logging.debug(str(e).split('\n')[0])

    def _transfer_funds(
            self,
            debit_account_id,
            credit_account_id,
            amount
            ):
        with self.connection.begin():
        #if True:

            # lock the table
            '''
            sql = f'LOCK balances IN ACCESS EXCLUSIVE MODE' # FOR UPDATE'
            logging.debug(sql)
            self.connection.execute(sql)
            '''

            # first we get the account balances
            sql = f'SELECT balance FROM balances WHERE account_id = {debit_account_id} FOR UPDATE'
            logging.debug(sql)
            results = self.connection.execute(sql)
            debit_account_balance = results.first()['balance']

            sql = f'SELECT balance FROM balances WHERE account_id = {credit_account_id} FOR UPDATE'
            logging.debug(sql)
            results = self.connection.execute(sql)
            credit_account_balance = results.first()['balance']

            # insert the transaction
            sql = f'INSERT INTO transactions (debit_account_id, credit_account_id, amount) VALUES ({debit_account_id}, {credit_account_id}, {amount})'
            logging.debug(sql)
            self.connection.execute(sql)

            # update the balances
            sql = f'UPDATE balances SET balance={debit_account_balance - amount} WHERE account_id = {debit_account_id}'
            logging.debug(sql)
            self.connection.execute(sql)

            sql = f'UPDATE balances SET balance={credit_account_balance + amount} WHERE account_id = {credit_account_id}'
            logging.debug(sql)
            self.connection.execute(sql)
