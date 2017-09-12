"""
Run EnergyPlus with random calibration parameters.

Author: Zhiang Zhang

First Created: Sept 1st, 2017
Last Updated: Sept 1st, 2017
"""
import os
import subprocess
import csv
import numpy as np

from BayCab4BEM.runSimulator import SimulatorRunWorker
from shutil import copyfile

EPLUS_OUTFILE_NAME = 'eplusout.csv' # This name varies for different version of Eplus

class EnergyPlusRunWorker(SimulatorRunWorker):
	"""
	The class is responsible for running one instance of EnergyPlus with a new set of values for the
	calibration parameters. 
	"""

	def updateWithThisInstanceOutput(self, baseInputFilePath, targetParaInfo, natModifyValues, 
									targetOutputInfo, globalList, globalLock, stdModifyValues, 
									jobID, baseWorkingDir, simulatorExeInfo):
		"""
		The method create a new simulation input file, run the simulation, extract relavent outputs 
		from the raw output files, and update the global results container globalList with the outputs. 
		This method varies for different simulators. 

		Args:
		    baseInputFilePath: str
				The path to the base simulator input file.
			targetParaInfo: list
				A 3-D list, where each row corresponds to the parameter(s) that should be changed to the 
				same values. Each item of each row is corresponding to one value to be changed. 
				Each item describes how to locate the parameter. Index 0 is the the Eplus object
				name (like material), index 1 is the name of the object (like material1),
				index 2 is how may lines below the line of the name of the object that
				should be changed. 
			natModifyValues: 1-D np.ndarray
				The new values to the calibration parameters in their native range.
			targetOutputInfo: list
				A 2-D list, where each row corresponds to one output type, the contents of each row
				describe how to locate the output. Index 0 of each row is the name of the output
				as dispaly in the eplusout.csv file. 
			globalList: list
				The shared result container, with col 0 the std calibration parameter inputs 
				(argument stdModifyValues), col 1 the outputs (a np.ndarray with each row corresponds 
				to one timestep). The ultimate goal of this method is to add simulation outputs 
				from this run to this globalList. 
			globalLock: multiprocessing.Lock
				The shared lock for all threads.
			stdModifyValues: 1-D np.ndarray
				The new values to the calibration parameters in 0-1 range.
			jobID: int
				An ID, mainly to avoid name conflicts. 
			baseWorkingDir: str
				The simulator base working dir. 
			simulatorExeInfo: list
				A list of two strings, the first one the path to Eplus exe file, the second one the
				weather file path. 

		Ret: None
		"""
		# Make a new working dir for just this run
		thisRunWorkingDir = baseWorkingDir + '/run%d'%(jobID);
		while os.path.isdir(thisRunWorkingDir):
			thisRunWorkingDir += '-dup';
		os.makedirs(thisRunWorkingDir);
		# Copy the base idf file to thisRunWorkingDir
		thisRunIDFFilePath = thisRunWorkingDir + '/run%d.idf'%(jobID);
		copyfile(baseInputFilePath, thisRunIDFFilePath);
		# Make change to the idf file
		# Change the str to int
		for targetParaInfoRow in targetParaInfo:
			for targetParaInfoItem in targetParaInfoRow:
				targetParaInfoItem[2] = int(targetParaInfoItem[2]);
		self._makeChangeToIDFFile(thisRunIDFFilePath, targetParaInfo, natModifyValues);
		# Run Eplus
		eplus_process = self._createEplusRun(simulatorExeInfo[0], simulatorExeInfo[1], 
						                  thisRunIDFFilePath, thisRunWorkingDir, thisRunWorkingDir);
		eplus_process.wait();
		# Extract output from raw output files
		extractedOutput = self._extractOutputFromRawFile(thisRunWorkingDir + '/' + EPLUS_OUTFILE_NAME,
														 targetOutputInfo)
		# Add the results to the globalList
		globalLock.acquire() # will block if lock is already held
		globalList.append([stdModifyValues, extractedOutput]);
		globalLock.release()

	def _extractOutputFromRawFile(self, outputFilePath, targetOutputInfo):
		"""
		Extract the target outputs from the raw output file

		Args:
			outputFilePath: str
				The output file path.
			targetOutputInfo: list
				A 2-D list, where each row corresponds to one output type, the contents of each row
				describe how to locate the output. Index 0 of each row is the name of the output
				as dispaly in the eplusout.csv file. 
		
		Ret:np.ndarray
			A 2-D array with each row the results of the time step, each col the type of output. 
		"""
		with open(outputFilePath, 'rt') as csvfile:
			r = csv.reader(csvfile, delimiter=',');
			lineCount = 0;
			tgtColsInOutput = [];
			extractedOutput = [];
			for line in r:
				line = [item.lower() for item in line];
				if lineCount == 0:
					# Locate the cols of the target output
					header = line;
					for i in range(len(targetOutputInfo)):
						try:
							targetOutputInfoThis = targetOutputInfo[i][0].lower();
							tgtColsInOutput.append(header.index(targetOutputInfoThis));
						except ValueError:
							pass;
				else:
					thisLineExtractedOutput = [];
					for colNum in tgtColsInOutput:
						thisLineExtractedOutput.append(float(line[colNum]));
					extractedOutput.append(thisLineExtractedOutput);
				lineCount += 1;
		extractedOutput = np.array(extractedOutput);
		return extractedOutput;

	def _createEplusRun(self, eplus_path, weather_path, idf_path, out_path, eplus_working_dir):
		"""
        Create a EnergyPlus run.

        Args:
        	eplus_path: str
        		The EnergyPlus executable file path.
        	weather_path: str
        		The .epw weather file path.
        	idf_path: str
        		The .idf file path.
        	out_path: str
        		The Eplus results output path.
        	eplus_working_dir: str
        		The dir where .idf file is stored. 

        Ret: a subprocess object. 
        """
		openNewTerminalCMD = ['xterm', '-e'];
		eplus_process = subprocess.Popen(openNewTerminalCMD + [eplus_path, '-w', weather_path, 
										'-d', out_path, '-r', idf_path],
										preexec_fn = os.setpgrp);
		return eplus_process;

	def _makeChangeToIDFFile(self, thisRunIDFFilePath, targetParaInfo, natModifyValues):
		tgtObjectList = [];
		tgtNameList = [];
		for targetParaInfoRow in targetParaInfo:
			for targetParaInfoItem in targetParaInfoRow:
				tgtObjectList.append(targetParaInfoItem[0]);
				tgtNameList.append(targetParaInfoItem[1]);

		contents = None
		with open(thisRunIDFFilePath, 'r', encoding = 'ISO-8859-1') as idf:
			contents = idf.readlines();
			remember_idx = -1;
			foundObject = False;
			foundedObject = None;
			foundName = False;
			i = 0;
			for line in contents:
				effectiveContent = line.strip().split('!')[0] # Ignore contents after '!'
				effectiveContent = effectiveContent.strip().split(',')[0] # Remove tailing ','
				if effectiveContent in tgtObjectList:
					foundObject = True;
					foundedObject = effectiveContent;
				if ";" in effectiveContent: # Apperance of ';' means the end of an object
					foundObject = False;
					foundedObject = None;
				if effectiveContent in tgtNameList:
					if foundObject:
						for targetParaInfoRow_i in range(len(targetParaInfo)):
							targetParaInfoRow = targetParaInfo[targetParaInfoRow_i];
							for targetParaInfoItem_i in range(len(targetParaInfoRow)):
								targetParaInfoItem = targetParaInfoRow[targetParaInfoItem_i];
								if (targetParaInfoItem[0] == foundedObject  
									and targetParaInfoItem[1] == effectiveContent):
									remember_idx = i + targetParaInfoItem[2];
									changeIndex = targetParaInfoRow_i;
				if i == remember_idx:
					toBeChangedLine = contents[i];
					# Determine should this line end with ',' or ';'
					tailingMark = toBeChangedLine.strip().split('!')[0].strip()[-1];
					# Change the content
					contents[i] = str(natModifyValues[changeIndex]) + \
                				tailingMark + ' !- Calibration parameter %d'%(changeIndex) + '\n';
					foundObject = False;
				i += 1;
		with open(thisRunIDFFilePath, 'w', encoding = 'ISO-8859-1') as idf:
			idf.writelines(contents);
    