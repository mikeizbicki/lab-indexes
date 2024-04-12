# Lab: Indexes

This lab will continue our running example of the double entry accounting system.
In this lab, you will:
1. learn more edge cases about when indexes can speed up queries, and
1. get practice using the EXPLAIN command to debug performance problems.

<img src=img/explain-analyze.jpg width=300px />

## Problem Setup

Clone the repo and bring up the containers.

The data is stored in TSV (tab separated value) files inside the `data` folder.
Load it into postgres with the following incantation.
```
$ docker-compose exec -T pg psql -c "COPY accounts(name, description) FROM stdin DELIMITER E'\t' CSV HEADER" < data/accounts.tsv
```

## Exploring the default index

Connect to psql with the command
```
$ docker-compose exec pg psql
```
and run the psql command
```
\d+ accounts
```
This will show you the schema of the accounts table.
Notice that a new TEXT column `description` has been added to the table,
and an index named `accounts_pkey` was created automatically by the PRIMARY KEY.

The command
```
SELECT * FROM accounts WHERE account_id=13000;
```
will select all of the information about the account with `account_id=13000`.
The *query plan* is the imperative algorithm that postgres will use to evaluate this query.
You can find it by prepending the `EXPLAIN` command before the query like so:
```
EXPLAIN SELECT * FROM accounts WHERE account_id=13000;
```
Running the above command should give you output that looks something like
```
                                   QUERY PLAN
--------------------------------------------------------------------------------
 Index Scan using accounts_pkey on accounts  (cost=0.29..8.30 rows=1 width=281)
   Index Cond: (account_id = 13000)
(2 rows)
```
Observe that this query is using an index scan.
It should make sense to you that an index scan is the best we can do for this query (because an index only scan is not possible and a bitmap scan or sequential scan will both have more overhead).

Observe that the following query will use an index only scan (by computing the query plan with EXPLAIN).
```
SELECT account_id FROM accounts WHERE account_id=13000;
```

Observe that the following query plan will use an index scan.
```
SELECT * FROM accounts WHERE account_id>13000;
```
(It should make sense to you why a btree index allows inequality constraints.)

Now observe that the following query will use a sequential scan.
```
SELECT * FROM accounts WHERE account_id<13000;
```
The query above could technically be done with an index scan,
but postgres has determined that the overhead of an index scan is too great,
and a sequential scan will actually be more efficient.

<!--
We can verify that with the EXPLAIN(ANALYZE,BUFFERS) command.
Recall that EXPLAIN only computes the query plan, but EXPLAIN(ANALYZE,BUFFERS) actually runs the query and reports debug statistics
-->

## Indexing `names`

We currently have no indexes that can speed up queries with a condition on the `name` column like the following.
```
SELECT * FROM accounts WHERE name='APEX INVESTMENTS';
```
Use the EXPLAIN command to observe that this query will use a sequential scan.

Now run the following command.
```
CREATE INDEX ON accounts(name);
```
And observe that the SELECT query above will now use an index scan.

There are many other types of queries that we might want to perform on the `names` column besides equality queries.
For example, there are many accounts in this dataset whose name starts with the word APEX,
and it would be interesting to select all of these accounts.
There are many ways we can do that with SQL,
and they will each require different indexes.

### Method 1

Perhaps the most obvious method of extracting accounts whose name begins with `APEX` is to use the LIKE operator:
```
SELECT * FROM accounts WHERE name LIKE 'APEX%';
```
Unfortunately, if you EXPLAIN this query, you will see that your current index is not being used.
[Page 2 of the habr.com blog posts](https://habr.com/en/companies/postgrespro/articles/442546/) explains how different operator classes can be used to provide different functionality for indexes.
By default, the btree index only supports the <, <=, =, >, and >= operators, and does not support the LIKE operator.

We can create a btree index that supports the LIKE operator by defining an index that uses the `text_pattern_ops` operator class like so:
```
CREATE INDEX ON accounts(name text_pattern_ops);
```
Now, if you re-EXPLAIN the SELECT query above, you should see it using the index.

### Method 2

Another reasonable method of extracting accounts whose name begins with `APEX` is to split the name into words, and check that the first word is equal to `APEX`.
In postgres, the built-in `split_part` function can be used to extract words from text.
The following SQL query follows this strategy.
```
SELECT * FROM accounts WHERE split_part(name, ' ', 1)='APEX';
```
Unfortunately, this query cannot use either of our indexes created so far.

In order for postgres to use an index, any function calls that are applied to the columns must also be contained in the index.
For example, id you create the following index
```
CREATE INDEX ON accounts(split_part(name, ' ', 1));
```
then the SELECT query above will be able to use the index.

### Method 3

Perhaps the least obvious way of finding words that start with `APEX` is to rely on the >= and < operators.
The following query takes advantage of the ASCIIbetical ordering of the letters to find all companies that start with `APEX`.
```
SELECT * FROM accounts WHERE name >= 'APEX' AND name < 'APEY';
```
Observe that this query does not need a new index.
The default btree index we created at the beginning works well in this case. 

The takeaway from this is that you must be very careful when writing your SQL SELECT queries to ensure that they are compatible with the indexes you have available.

## Submission

There are 348 accounts whose `name` column ends in the word `Management` (case insensitive).
Write a SELECT query that lists these account names.
(You know it's correct if you get the right number.)
Then create an index that will allow your SELECT query to use any of the non-sequential scans (i.e. index scan, index only scan, or bitmap scan).

Submit your SELECT query and CREATE INDEX commands to sakai.

## Final Exam Prep

There is nothing to submit for this section, but it will review an important concept for the final exam.

Consider the following query
```
SELECT * FROM accounts where name LIKE 'APEX%' OR account_id > 13000;
```
If you use EXPLAIN to get the query plan, you should see something like
```
                                    QUERY PLAN
----------------------------------------------------------------------------------
 Bitmap Heap Scan on accounts
   Recheck Cond: ((name ~~ 'APEX%'::text) OR (account_id > 13000))
   Filter: ((name ~~ 'APEX%'::text) OR (account_id > 13000))
   ->  BitmapOr
         ->  Bitmap Index Scan on accounts_name_idx
               Index Cond: ((name ~>=~ 'APEX'::text) AND (name ~<~ 'APEY'::text))
         ->  Bitmap Index Scan on accounts_pkey
               Index Cond: (account_id > 13000)
(8 rows)
```
Notice that the above query plan uses two indexes:
1. `accounts_name_idx`, created on `accounts(name)` and
1. `accounts_pkey`, created on `accounts(account_id)`.
The names of your indexes may be different (due to you having created different indexes while experimenting with the submission problem), but you should still have two indexes listed.

There is no single index that will work for this query to enable an efficient index scan or an index only scan, and the bitmap scan is the best we can do.
You can partially verify this claim by running the following two commands
```
CREATE INDEX ON accounts(name text_pattern_ops, account_id);
CREATE INDEX ON accounts(account_id, name text_pattern_ops);
```
and observing that the SELECT query above will continue to use the bitmap scan.

Before the final exam, you should ensure you understand why the query above can be efficiently implemented with a bitmap scan, but cannot be implemented with an index or index only scan.
