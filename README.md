# WebCensusNotebook

A Python3 jupyter notebook for interacting with Princeton WebTAP's Web Census.

If you'd like access to the beta of our 

To get started, open `demo.ipynb`. There you will find how to use our libraries to access our web census data.

Any methods called in `demo.ipynb` that save their output will write their output to the `results/` directory.

## Supported features:
* For every FirstParty, get ThirdParty resources on the visited page.
* For every ThirdParty, get each FirstParty it is embedded on and the URLs of the ThirdParty's resources.
* Tracker status for a given resource.
* Analysis by Alexa category.
* Get cookies set by a particular ThirdParty (v1)

## Upcoming features:
* Get cookie sync events on each FirstParty
* Check for third party fingerprinting

## Current available data:
* One million sites, October 2016
* One million sites, January 2016

## Data coming soon:
* One million sites, April 2017
