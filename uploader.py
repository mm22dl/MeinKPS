#! /usr/bin/python
# -*- coding: utf-8 -*-

"""
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Title:    uploader

    Author:   David Leclerc

    Version:  0.1

    Date:     01.07.2017

    License:  GNU General Public License, Version 3
              (http://www.gnu.org/licenses/gpl.html)

    Overview: This is a script that uploads all reports to a server.

    Notes:    ...

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

# LIBRARIES
import os
import ftplib



# USER LIBRARIES
import logger
import reporter



# Define instances
Logger = logger.Logger("uploader")



# CLASSES
class Uploader(object):

    def __init__(self):

        """
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            INIT
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        """

        # Define report
        self.report = reporter.REPORTS["ftp"]



    def upload(self, ftp, path, ext = None):

        """
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            UPLOAD
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        """

        # Get all files from path
        files = os.listdir(path)

        # Get inside path
        os.chdir(path)

        # Upload files
        for f in files:

            # If file
            if os.path.isfile(f):

                # Verify extension
                if "." + ext != os.path.splitext(f)[1]:

                    # Skip file
                    continue

                # Info
                Logger.debug("Uploading: '" + os.getcwd() + "/" + f + "'")

                # Open file
                F = open(f, "r")

                # Upload file
                ftp.storlines("STOR " + f, F)

                # Close file
                F.close()

            # If directory
            elif os.path.isdir(f):

                # If directory does not exist
                if f not in ftp.nlst():

                    # Info
                    Logger.debug("Making directory: '" + f + "'")

                    # Make directory
                    ftp.mkd(f)

                # Move in directory
                ftp.cwd(f)

                # Upload files in directory
                self.upload(ftp, f, ext)

        # Get back to original directory on server
        ftp.cwd("..")

        # Locally as well
        os.chdir("..")



    def run(self):

        """
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            RUN
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        """

        # Test if report is empty before proceding
        if not self.report.isValid():
            raise IOError("Invalid FTP report.")

        # Instanciate an FTP object
        ftp = ftplib.FTP(self.report.get(["Host"]),
                         self.report.get(["User"]),
                         self.report.get(["Password"]))

        # Move to directory
        ftp.cwd(self.report.get(["Path"]))

        # Define path to files
        path = reporter.path.EXPORTS.path

        # Upload files
        self.upload(ftp, path, "json")



def main():

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        MAIN
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    """

    # Define uploader
    uploader = Uploader()

    # Run it
    uploader.run()



# Run this when script is called from terminal
if __name__ == "__main__":
    main()