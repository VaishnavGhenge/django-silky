.. silk documentation master file, created by
   sphinx-quickstart on Sun Jun 22 13:51:12 2014.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Silk
================================

.. toctree::
   :maxdepth: 2

   quickstart
   profiling
   configuration
   troubleshooting

Silk is a live profiling and inspection tool for the Django framework. Silk intercepts and stores HTTP requests and database queries before presenting them in a user interface for further inspection:

.. image:: /images/summary.png

A **live demo** is available `here`_.

.. _here: http://mtford.co.uk/silk/

Features
--------

- Inspect HTTP requests and responses

  - Query parameters

  - Headers

  - Bodies

  - Execution Time

  - Database Queries

    - Number

    - Time taken

- SQL query inspection

  - Queries grouped by shape across all requests, with p95 time and DB time per table

  - Hotspots: lines of application code ranked by the database time they cause

  - N+1 and duplicate query detection, with a likely fix at the calling line

- Compare two requests, or two time ranges such as before and after a deploy

- Profiling of arbitrary code blocks via a Python context manager and decorator

  - Execution Time

  - Database Queries

  - Can also be injected dynamically at runtime e.g. if read-only dependency.

- Authentication/Authorisation for production use

- Per-browser settings: theme, editor links, and thresholds for slow requests and N+1


Requirements
------------

* Django: 5.2, 6.0, 6.1
* Python: 3.10, 3.11, 3.12, 3.13, 3.14, 3.15
