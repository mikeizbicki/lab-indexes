# Lab: MVCC Implementation Details

This lab will continue our running example of the double entry accounting system we started with the [lab-consistency]() and [lab-transactions]().
In this lab, you will:
1. observe how modifying data creates dead tuples,
2. learn about the HOT tuple update optimization,
3. learn about the performance impact of VACUUM and VACUUM FULL.

<img src=img/bloat.jpg width=400px />

## Problem Setup

Open the `docker-compose.yml` file and modify the port of the `pg` service.
We will only be using one database in this lab.

Then bring up the database.
```
$ docker-compose build
$ docker-compose up -d
```
In order to explore how postgres stores data,
we will connect to the container using a shell instead of psql.
```
$ docker-compose exec pg bash
```
The `PGDATA` environment variable contains the path where postgres stores all of its data.
Enter that path and view the contents.
```
$ cd $PGDATA
$ pwd
$ ls
```
[The Internals of Postgres Book, Section 1.2](http://www.interdb.jp/pg/pgsql01/02.html) contains an overview of each of these files.
You are not responsible for memorizing their purpose, but you are responsible for being able to read through the documentation about these files if necessary.

For us, the most important file is the `base` directory.
It contains all databases in the postgres cluster, each represented by a directory.
You should see three folders, although the might be named differently than mine below.
```
$ ls base
1  13480  13481
```
How do we know which of these our data is stored in?
Start psql.
```
$ psql
```
Notice that because we are currently inside of the container, there is no need to pass any url to psql to perform the connection.
Postgres stores information about the databases in the cluster in the `pg_database` relation.
View it with the following command.
```
SELECT oid,datname FROM pg_database;
  oid  |  datname
-------+-----------
 13481 | postgres
     1 | template1
 13480 | template0
```
The `postgres` docker repo by default has 3 databases in the cluster.
The `template0` and `template1` databases are used internally,
and the `postgres` database is what you're currently connected to.
In postgres, anything that needs to be stored on the hard drive will get an *Object ID* (OID) associated to it,
and the oid will be the name of that file or folder.
Thus, all the information for our database can be found in the `$PGDATA/base/13481` folder.

Leave psql, and run the following command to see the files that make up the `postgres` database
```
$ ls base/13481
```
You should see a lot of files.
Each of these files will start with a number, which is the OID of the object that file represents.

Our goal is to be able to measure how much disk space each table in our database takes up,
and in order to do that, we need to find the OID of each table.
Go back into psql.
```
$ psql
```
Run `\d` to view all of the relations in the database.
You should see only 5: 3 tables, and 2 sequences (sequences store information related to the SERIAL type we are using as primary keys in the `accounts` and `transactions` tables).
Notice that there are many things besides relations that get assigned an OID and take up disk space,
but we won't care about any of these other objects in this class.

> **Task:**
> Your first task is to find the OID of each of the three tables in the database.
> [The Internals of Postgres Book, Section 1.2](http://www.interdb.jp/pg/pgsql01/02.html#123-layout-of-files-associated-with-tables-and-indexes) contains a query that you can use to do this.
> Make a note of these three OIDs.
> You'll have to reference them later in the lab.

<!--
postgres=# SELECT relname, oid, relfilenode FROM pg_class WHERE relname = 'accounts';
 relname  |  oid  | relfilenode
----------+-------+-------------
 accounts | 16386 |       16386
(1 row)

postgres=# SELECT relname, oid, relfilenode FROM pg_class WHERE relname = 'balances';
 relname  |  oid  | relfilenode
----------+-------+-------------
 balances | 16415 |       16415
(1 row)

postgres=# SELECT relname, oid, relfilenode FROM pg_class WHERE relname = 'transactions';
   relname    |  oid  | relfilenode
--------------+-------+-------------
 transactions | 16397 |       16397
(1 row)

postgres=# SELECT pg_relation_filepath('accounts');
 pg_relation_filepath
----------------------
 base/13481/16386
(1 row)

postgres=# SELECT pg_relation_filepath('balances');
 pg_relation_filepath
----------------------
 base/13481/16415
(1 row)

postgres=# SELECT pg_relation_filepath('transactions');
 pg_relation_filepath
----------------------
 base/13481/16397
(1 row)
-->

## Observing `accounts`

For me, the `accounts` table has OID 16386,
and so it is stored in the file `$PGDATA/base/13481/16386`.
Use the `ls -l` command to get the total size of the table.
```
ls -l base/13481/16386
-rw------- 1 postgres postgres 0 Apr  5 06:05 base/13481/16386
```
At this point, you should get that it takes up 0 bytes because we haven't inserted anything yet.

Now we'll insert some accounts using the `create_accounts.py` script we introduced in the last lab.
This script is only available on the lambda server (and not inside the container),
so you'll have to exit the container.

Recall that in order to use your `Ledger` library in python,
you have to first set the `EXPORTPATH` environment variable.
On the lambda server, run
```
$ export PYTHONPATH=.
```
Then run the following command.
(You'll have to change the `9999` to whatever port number you specified in the `docker-compose.yml` file.)
```
$ time python3 scripts/create_accounts.py postgresql://postgres:pass@localhost:9999 --num_accounts=10000
```
This command inserts 10000 new user accounts into the accounts table.

> **Note:**
> I like to use the `time` command to time any command that will take a long time to run.
> We won't actually need the time for this assignment, but there's no downside to measuring it.
> My execution took 47 seconds.

Now go back in the container and re-check the size of the `accounts` table.
```
$ ls -l $PGDATA/base/13481/16386*
-rw------- 1 postgres postgres 524288 Apr  4 22:19 base/13481/16386
-rw------- 1 postgres postgres  24576 Apr  4 22:18 base/13481/16386_fsm
```
Notice that it is non-zero, and that the *free space map* (FSM) file has been created as well.
Recall that the FSM stores precomputed values of the amount of free space in each page,
and this file is used by postgres to quickly find a page that it can insert a tuple into.

Let's count how many pages are in the table.
My `16386` file above uses `524288` bytes, and each page is 8kb (i.e. 8192 bytes).
Based on these values, you can use python to compute the number of pages:
```
$ python3
>>> 524288/8192
64.0
```
Notice that the filesize is exactly a multiple of 8192.
This will always be the case for every file.

## Observing `transactions` and `balances`

The `accounts` table is relatively uninteresting.
Our test scripts only ever run the INSERT command,
and so there is no opportunity for dead tuples.
The `transactions` table also will only have INSERT commands run.
The `balances` table, however, is more interesting.
Inside of our `Ledger/__init__.py` file,
whenever we INSERT to `transactions`, we perform two UPDATEs to `balances`.
So we should expect to see dead tuples in the `balances` table after runing this script.
In this section, we will observe these dead tuples and measure their affect on our performance.

Before we insert data, we should check the size of the `balances` and `transactions` tables.
Recall that to do this, you'll need to enter the container and run `ls -l` on the files that store these tables.

> **Warning:**
> Don't proceed to the next steps until you've completed this step.
> You'll be measuring the size of these files quite a bit,
> and so it's important you know how to do it.

Now leave the container and return to the lambda server.

The `lots_of_data.sh` script will insert 1000,000 transactions into our database,
and so call 200,000 UPDATE commands on `balances`.
View the code, and make sure you understand what it's doing.
```
$ cat scripts/lots_of_data.sh
```
Now run it.
```
$ time sh scripts/lots_of_data.sh postgresql://postgres:pass@localhost:9999
```
It should take about two minutes to run.

Once again, view the size of the containers.
For me, the appropriate commands and outputs looked like:
```
$ ls -l $PGDATA/base/13481/16415*
-rw------- 1 postgres postgres 1220608 Apr  4 22:29 base/13481/16415
-rw------- 1 postgres postgres   24576 Apr  4 22:29 base/13481/16415_fsm
$ ls -l $PGDATA/base/13481/16397*
-rw------- 1 postgres postgres 52682752 Apr  4 22:27 base/13481/16397
-rw------- 1 postgres postgres    32768 Apr  4 22:27 base/13481/16397_fsm
```
And the `balances` table (OID 16415) had 1220608/8192=149 pages.
<!--
You should make a note of how many pages your `balances` table has,
as this will be important later.
-->

To measure the number of dead tuples, connect to psql and run the following command.
```
SELECT n_live_tup, n_dead_tup, relname FROM pg_stat_user_tables;
```
Which should give output similar to
```
 n_live_tup | n_dead_tup |   relname
------------+------------+--------------
      10000 |      14149 | balances
    1000000 |          0 | transactions
      10000 |          0 | accounts
```
The following things should make sense to you:
1. The number of live tuples in the `balances` and `accounts` tables is each 10000,
    which is the number of accounts that we inserted with the `create_accounts.py` command.
    (We INSERT one row into `balances` for each INSERT into `account`.)
1. The `transactions` table has 1e6 rows because that's the number of transactions that we inserted.
1. The `transactions` and `accounts` tables each have 0 dead tuples, because we have never called a DELETE or UPDATE on these tables.

But the number of dead tuples in `balances` should look weird to you.
That's because:
1. We call two UPDATEs on `balances` for every insert into `transactions`.
1. For every UPDATE, we create 1 dead tuple according to the procedure outlined at <http://www.interdb.jp/pg/pgsql05/03.html#533-update>.
1. Therefore we should have 2e6 dead tuples, but we have a number much smaller.
    (I got 14149, but your number is likely to be different.)

Why is that?

The answer is an optimization postgres implements called a *heap only tuple* (HOT) tuple.
For our purposes right now, there are two important things to know about the HOT tuple optimization:
1. It performs a "mini vacuum" that deletes all dead tuples in a page after an UPDATE operation finishes.
    This mini vacuum is what is deleting most of the dead tuples we "should" be observing.
    The `pg_stat_user_tables` relation that we examined above also has a column `n_tup_hot_upd` that records how many times the HOT tuple optimization triggered,
    and if you run the following command:
    ```
    SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables;
    ```
    you should see that it triggered a lot.
1. The HOT tuple optimization is only available on columns that do not have indexes.
    In the next section, you will rerun these commands after creating an index and observe how the index can hurt UPDATE performance by removing the HOT optimization.

> **Note:**
> HOT tuples are described in detail in [Chapter 7 of our textbook](http://www.interdb.jp/pg/pgsql07.html).
> For the final exam, you are responsible for understanding how HOT tuples work in detail, but we will not be going over them in lecture.

<!--
```
postgres=# CREATE EXTENSION pgstattuple;
CREATE EXTENSION
postgres=# \x
postgres=# SELECT * FROM pgstattuple('transactions');
-[ RECORD 1 ]------+---------
table_len          | 52682752
tuple_count        | 1000000
tuple_len          | 41000000
tuple_percent      | 77.82
dead_tuple_count   | 0
dead_tuple_len     | 0
dead_tuple_percent | 0
free_space         | 388388
free_percent       | 0.74
postgres=# SELECT * FROM pgstattuple('accounts');
-[ RECORD 1 ]------+-------
table_len          | 524288
tuple_count        | 10000
tuple_len          | 460000
tuple_percent      | 87.74
dead_tuple_count   | 0
dead_tuple_len     | 0
dead_tuple_percent | 0
free_space         | 2496
free_percent       | 0.48
postgres=# SELECT * FROM pgstattuple('balances');
-[ RECORD 1 ]------+--------
table_len          | 1253376
tuple_count        | 10000
tuple_len          | 334804
tuple_percent      | 26.71
dead_tuple_count   | 3927
dead_tuple_len     | 131463
dead_tuple_percent | 10.49
free_space         | 531044
free_percent       | 42.37
```
See: <https://stackoverflow.com/questions/51156552/are-dead-rows-removed-by-anything-else-than-vacuum>
-->

Let's remove the (relative few) dead tuples using the VACUUM command:
```
postgres=# VACUUM balances;
```
And then observe that there are now no dead tuples.
```
postgres=# SELECT n_live_tup, n_dead_tup, relname FROM pg_stat_user_tables;
```
Which should give output similar to
```
 n_live_tup | n_dead_tup |   relname
------------+------------+--------------
      10000 |          0 | balances
    1000000 |          0 | transactions
      10000 |          0 | accounts
```

<!--
```
$ ls -l base/13481/16415*
-rw------- 1 postgres postgres 1253376 Apr  4 22:52 base/13481/16415
-rw------- 1 postgres postgres   24576 Apr  4 22:52 base/13481/16415_fsm
-rw------- 1 postgres postgres    8192 Apr  4 22:52 base/13481/16415_vm
```

```
postgres=# SELECT pg_relation_filepath('balances');
 pg_relation_filepath 
----------------------
 base/13481/16415
(1 row)

postgres=# VACUUM FULL balances;
VACUUM

postgres=# SELECT * FROM pgstattuple('balances');
-[ RECORD 1 ]------+-------
table_len          | 450560
tuple_count        | 10000
tuple_len          | 334804
tuple_percent      | 74.31
dead_tuple_count   | 0
dead_tuple_len     | 0
dead_tuple_percent | 0
free_space         | 9020
free_percent       | 2

postgres=# SELECT pg_relation_filepath('balances');
 pg_relation_filepath 
----------------------
 base/13481/16435
(1 row)

```

```
$ ls -l base/13481/16415*
ls: cannot access 'base/13481/16415*': No such file or directory
$ ls -l base/13481/16435*
-rw------- 1 postgres postgres 450560 Apr  4 22:56 base/13481/16435
```

Talk about durability here.
-->

## Observing `accounts` with an index

We will now repeat the steps above on a table that has an index,
and see how that index drastically changes performance.

First restart postgres.
```
$ docker-compose down
$ docker-compose up -d
```
Then enter psql and create an index on `balances(balance)`.
```
$ docker-compose exec pg psql
postgres=# CREATE INDEX ON balances(balance);
CREATE INDEX
```
Now, all of our steps will be the same as above.
Add the data.
```
$ time python3 scripts/create_accounts.py --num_accounts=10000 postgresql://postgres:pass@localhost:9999
$ time sh scripts/lots_of_data.sh postgresql://postgres:pass@localhost:9999
```

<!--
```
postgres=# select max(balance) from balances;
   max
----------
 29520.00
(1 row)

Time: 0.636 ms
postgres=# explain (analyze, buffers) select max(balance) from balances;
                                                                              QUERY PLAN
----------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Result  (cost=0.49..0.50 rows=1 width=32) (actual time=0.081..0.084 rows=1 loops=1)
   Buffers: shared hit=4
   InitPlan 1 (returns $0)
     ->  Limit  (cost=0.43..0.49 rows=1 width=16) (actual time=0.072..0.074 rows=1 loops=1)
           Buffers: shared hit=4
           ->  Index Only Scan Backward using balances_balance_idx on balances  (cost=0.43..77028.09 rows=1176438 width=16) (actual time=0.070..0.070 rows=1 loops=1)
                 Index Cond: (balance IS NOT NULL)
                 Heap Fetches: 1
                 Buffers: shared hit=4
 Planning Time: 0.187 ms
 Execution Time: 0.123 ms
(11 rows)

Time: 0.817 ms
```
-->

And check the sizes of the `balances` table.
```
$ ls -l base/13481/16415*
-rw------- 1 postgres postgres 57540608 Apr  4 23:15 base/13481/16415
-rw------- 1 postgres postgres    32768 Apr  4 23:15 base/13481/16415_fsm
```
(Again, due to the nondeterminism of the `lots_of_data.sh` script, your numbers may be slightly different.)

Notice that the size of the `balances` table is about 50x bigger.
(It's easy to lose track of the fact that we've added an extra order of magnitude.)

Indexes have their own separate OIDs in postgres,
and are stored in their own files.
Therefore the 50x size explosion above doesn't measure the actual size of the index.
To check its size, first find it's file location:
```
postgres=# SELECT pg_relation_filepath('balances_balance_idx');
 pg_relation_filepath
----------------------
 base/13481/16425
```
Then measure the size of that file
```
$ ls -l $PGDATA/base/13481/16425*
-rw------- 1 postgres postgres 59187200 Apr  4 23:17 base/13481/16425
```
That's 59MB.
In total, creating this index caused a table that was previously taking only about 1MB of disk space to now take up 116MB (57 for the table itself, and 59 for the index).
Disk space is cheap, and so for most problems a 100x explosion in filesize is not a problem.
But for very large datasets, this could be disasterous.

Let's now observer why the filesize is so bloated.
Rerun our command to measure the number of dead tuples:
```
postgres=# SELECT n_live_tup, n_dead_tup, relname FROM pg_stat_user_tables;
 n_live_tup | n_dead_tup |   relname
------------+------------+--------------
      10000 |    2000000 | balances
    1000000 |          0 | transactions
      10000 |          0 | accounts
```
We are now getting the predicted 2e6 dead tuples in the `balances` table because the HOT tuple optimization cannot fire, and so no mini-vacuum ever cleans the table.

Let's run the VACUUM manually.
```
postgres=# VACUUM balances;
VACUUM
```
And now observe there are no dead tutples.
```
postgres=# SELECT n_live_tup, n_dead_tup, relname FROM pg_stat_user_tables;
 n_live_tup | n_dead_tup |   relname
------------+------------+--------------
      10000 |          0 | balances
    1000000 |          0 | transactions
      10000 |          0 | accounts
(3 rows)
```
Leave psql, and use the `ls -l` commands to measure the file size of the table and index.
```
$ ls -l base/13481/16415*
-rw------- 1 postgres postgres 57540608 Apr  5 04:41 base/13481/16415
-rw------- 1 postgres postgres    32768 Apr  5 04:33 base/13481/16415_fsm
-rw------- 1 postgres postgres     8192 Apr  5 04:41 base/13481/16415_vm
$ ls -l base/13481/16425*
-rw------- 1 postgres postgres 59187200 Apr  5 04:41 base/13481/16425
```
Notice that the filesizes have not changed at all.
Recall that VACUUMing never deletes pages, and so doesn't free up disk space.
To actually free up disk space, we need to run
```
postgres=# VACUUM FULL balances;
```
Notice that this command actually changes where the tables are stored on the harddrive.
If you try to measure the filesize using the old file paths
```
$ ls -l base/13481/16415*
$ ls -l base/13481/16425*
```
you will get errors about the file not existing.

You should first find the new paths to the files
```
postgres=# SELECT pg_relation_filepath('balances');
 pg_relation_filepath
----------------------
 base/13481/16426
(1 row
postgres=# SELECT pg_relation_filepath('balances_balance_idx');
 pg_relation_filepath
----------------------
 base/13481/16430
(1 row)
```
Then measure the size of those paths
```
root@7e1014af3511:/var/lib/postgresql/data# ls -l base/13481/16426*
-rw------- 1 postgres postgres 450560 Apr  5 04:43 base/13481/16426
root@7e1014af3511:/var/lib/postgresql/data# ls -l base/13481/16430*
-rw------- 1 postgres postgres 245760 Apr  5 04:43 base/13481/16430
```
After performing the VACUUM FULL, we've reduced the filesize from over 100MB to under 1MB!

The disadvantage of a VACUUM FULL is that it acquires an EXCLUSIVE LOCK on the table,
and so nothing can run concurrently.

### Measuring the benefit of the index

If the index causes so much table bloat,
why do we want it?

Let's say we need to find the largest account balance.
We can answer that question with a query that looks like
```
SELECT max(balance) FROM balances;
```
Without an index, this would require a full sequential scan of the table.
Previously, we saw that the table without an index used 149 pages of disk space,
and so we would have to read all of those pages.
As more information gets added to the table, this number would grow linearly.

With an index, however, we will use significantly fewer page accesses.

In class, we saw how to use the EXPLAIN command to compute the *query plan*.
This is the imperative algorithm that postgres will use to actually compute the query's results. 
There are many variations of the EXPLAIN command,
but one useful variation is `EXPLAIN(analyze,buffers)`.
In this variation, postgres will actually run the command, and report runtimes of each substep and the total number of pages accessed.
Run the following example in psql to measure the performance of our SELECT query above.
```
postgres=# EXPLAIN(analyze, buffers) SELECT max(balance) FROM balances;
                                                                           QUERY PLAN
-----------------------------------------------------------------------------------------------------------------------------------------------------------------
 Result  (cost=0.34..0.35 rows=1 width=32) (actual time=0.051..0.053 rows=1 loops=1)
   Buffers: shared hit=3
   InitPlan 1 (returns $0)
     ->  Limit  (cost=0.29..0.34 rows=1 width=16) (actual time=0.044..0.045 rows=1 loops=1)
           Buffers: shared hit=3
           ->  Index Only Scan Backward using balances_balance_idx on balances  (cost=0.29..514.41 rows=9950 width=16) (actual time=0.041..0.042 rows=1 loops=1)
                 Index Cond: (balance IS NOT NULL)
                 Heap Fetches: 1
                 Buffers: shared hit=3
 Planning Time: 0.176 ms
 Execution Time: 0.092 ms
(11 rows)
```
THe most import line in the above output is line 2, which reads
```
   Buffers: shared hit=3
```
Here, "Buffers" is a synonymn for "blocks" or "pages",
and so we were able to answer the `max` query by accessing only 3 pages instead of the full 149.

This number grows only logrithmically, and so will always be very small.
I've personally never seen a btree index query access more than 5 pages,
even on tables that occupy terabytes (and so have billions of pages).

## Autovacuum

So far we've seen:
1. Indexes are important for speeding up SELECT queries.
1. But indexes disable the HOT tuple optimization.
1. This can cause our table to have too many dead tuples.
1. Dead tuples lead to wasted disk space (and lots of other problems).
The autovacuum will help us minimize these drawbacks of indexes.

Examine the contents of the schema.
```
$ cat services/pg/sql/ledger-pg.sql
```
Notice that each of the CREATE TABLE commands is terminated with a clause that looks like
```
WITH (autovacuum_enabled = off)
```
So all of the databases you've previously been working with had the autovacuum tool disabled.
(By default, it is enabled for every table.)

Re-enable the autovacuum command by deleting these clauses from each CREATE TABLE command.
Then bring the database down, rebuild the database, and bring it back up.
It is important to remember to run the `docker-compose build` command---which you don't normally have to run---because you've changed the schema files.
If you don't rerun this command, then autovacuum will not be enabled on your new database.

Now create an index in this new database
```
$ docker-compose exec pg psql
postgres=# CREATE INDEX ON balances(balance);
CREATE INDEX
```
And add the data.
```
$ time python3 scripts/create_accounts.py --num_accounts=10000 postgresql://postgres:pass@localhost:9999
$ time sh scripts/lots_of_data.sh postgresql://postgres:pass@localhost:9999
```
Once the data is loaded, observe that there are now no dead tuples in your table.
```
postgres=# SELECT n_live_tup, n_dead_tup, relname FROM pg_stat_user_tables;
 n_live_tup | n_dead_tup |   relname
------------+------------+--------------
      10000 |          0 | balances
    1000000 |          0 | transactions
      10000 |          0 | accounts
```
The HOT optimization is not firing (and performing the corresponding mini vacuums).
But there are no dead tuples in your table.
That's because autovacuum automatically calls the VACUUM command when the table becomes too bloated.
Because the VACUUM command acquires only a SHARE UPDATE EXCLUSIVE lock,
it will not conflict with any concurrent SELECT/UPDATE/INSERT/DELETE commands.

For small datasets (say <1TB), the default settings of autovacuum generally work well.
For large datasets, autovacuum has many parameters that should be tuned for optimal performance.
A large company that uses postgres (like Instagram) would have multiple employees whose job is basically just tuning autovacuum.

<img src=autovacuum.jpg width=300px >

<!--
```
root@294274f36cc2:/# cd $PGDATA
root@294274f36cc2:/var/lib/postgresql/data# ls -l base/13481/16415*
-rw------- 1 postgres postgres 30015488 Apr  5 05:35 base/13481/16415
-rw------- 1 postgres postgres    24576 Apr  5 05:34 base/13481/16415_fsm
-rw------- 1 postgres postgres     8192 Apr  5 05:34 base/13481/16415_vm
root@294274f36cc2:/var/lib/postgresql/data# ls -l base/13481/16425*
-rw------- 1 postgres postgres 33226752 Apr  5 05:36 base/13481/16425
-rw------- 1 postgres postgres    24576 Apr  5 05:34 base/13481/16425_fsm
```
-->

## Submission

Write 1 paragraph into sakai about what you learned from the lab.
