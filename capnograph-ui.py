#!/usr/bin/env python

# Breath Sensor UI and Monitor Program Version 10.2

# Python 3.9.5 64-bit Windows



"""
Program for coordinating a TSI 5300 flow meter and Sprint IR6 20% CO2 meter for observation of a person's CO2 output in breaths. Provides a useful display to monitor data aquisition
and saves all readings and calculations  in a local .csv file. All user control may be performed within the UI, and seperate documentation provides detailed instructions. 
For use in breath analysis research at Texas A&M University.
"""



__author__ = "Joshua Hale"
#__copyright__ = 'Copyright {year}, {project_name}'
__credits__ = ["Joshua Hale"]
#__license__ = '{license}'
__version__ = "10.2"
__maintainer__ = "Joshua Hale"
__email__ = "averyhale95@gmail.com"
__status__ = "In Development"



### Imports Listed in line order of use by section
# Generic Imports
import collections
import re
import serial
import os
import csv
import sys
import socket

# Libraries
import pandas as pd
import pyqtgraph as pg

# Detailed Imports
from datetime import datetime
from time import sleep

# PyQt5 Imports
from PyQt5.QtCore import QObject, pyqtSignal, QSize, Qt, QThread
from PyQt5.QtWidgets import QMainWindow, QTabWidget, QSizePolicy, QGroupBox, QGridLayout, QLabel, QWidget, QLineEdit, QPushButton, QDialogButtonBox, QComboBox, QApplication
from PyQt5 import QtGui, QtSerialPort


### Import section for test files
df = pd.read_csv (r'Testing Breath File.csv')

dffl = df['Flow SLPM']
dffl = dffl.dropna()
dffl = dffl.reset_index(drop=True)
dfco = df['CO2 ppm']
dfco = dfco.dropna()
dfco = dfco.reset_index(drop=True)


### Class for custom timestamp X axis on plots
class TimeAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value) for value in values]



### Qobject class for reading the TSI 5300 Flow meter outputs in a dedicated thread
### Operated by using the enable boolean variables
### Started by runFlowSensor
### Emits a signal to be used for plot updates in the format (0, value)
class FlowSensorWorker(QObject):
    
    # Class variables
    enableVar = True                        # Set to False to send end thread signal and exit loop
    enableChk = False                       # Set to False for simulated flow, set to True for device readings
    finished = pyqtSignal()                 # Signal used to indicate thread has finished
    newData = pyqtSignal(int, float)        # Signal carrying new data reading. Sent once per cycle
    oldData = collections.deque([0.0], 5)   # Variable for holding msot recent readings in case of an error

    # Function for passing sensor object to this class
    # Use this when starting the class so that it has access to the sensor object
    def connectConn(self, conn):
        self.floCon = conn

    # Function for running the main sensor read loop
    # Will emit readings on sensor delivery or 20 times per second simulated until enableVar is made False
    def run(self):
        
        i = 0           # Iterator for simulated values
        count = 0       # Count variable for automatically requesting reading batches
        countMax = 250  # The number of readings before sending the meter a new request for 500 readings
                        # This must be < 500 to account for errors, but cannot be too low or the meter may freeze
        
        # Loop for simulating flow readings
        # Generates a lazy sine wave
        while(self.enableChk == False):
            if (self.enableVar == False):
                break
            sleep(0.05)
            self.newData.emit(0, dffl[i])
            i = i+1

        # Loop for reading flow meter output
        while(self.enableChk == True):
            if (self.enableVar == False):
                break
            
            # Send a command for a chunk of readings periodically based on count
            if (count < 1):
                count = countMax 
                self.floCon.sendall(b'DAFxx0475\r') # 'x' is the ascii command to request readings from the meter. Change the number for more or less readings per batch.

            # This block waits for new readings and interprets them. Bad reads or encoding errors shold skip to the exception and add a zero reading  
            try:
                newVal = re.findall('[+-]?\d+.\d+', str(self.floCon.recv(1024), "ascii"))
                self.oldData.append(newVal[0])
                self.newData.emit(0, float(newVal[0]))
                count = count - 1

            except:
                # Report failure and add a zero reading for post-processing cleanup. Sleep to allow meter to catchup in case of device lag.
                print("Failure to read Flow Meter reading:", (450 - count))
                self.newData.emit(0, float(self.oldData[-1]))
                sleep(0.05)
        
        print("Flow meter thread finished.")
        self.finished.emit()



### Qobject class for reading the SprintIR6s 20% CO2 meter in a dedicated thread
### Operated by using the enable boolean variables
### Started by runCoSensor
### Emits a signal to be used for plot updates in the format (1, value)
class CoSensorWorker(QObject):

    # Class variables
    enableVar = True                      # Set to False to sedn end thread signal and exit loop
    enableChk = False                     # Set to True to use device readings
    finished = pyqtSignal()               # Signal to indicate thread completion
    newData = pyqtSignal(int, float)      # Signal to carry new data emitted. Used once per cycle
    coCon = serial.Serial()               # Member variable for holding serial object. Can be modified to alter serial settings. Check Python Serial documentation for details.
    oldData = collections.deque([0.0], 5) # Variable for holding most recent readings in case of an error
    
    # Function for passing sensor object to this class
    # Use this when starting the class so that it has access to the sensor object 
    def connectConn(self, conn):
        self.coCon = conn

    # Function for running the main sensor read loop
    # Will emit readings on sensor delivery or 20 times per second simulated until enableVar is made False
    def run(self):
        
        i = 0   # Iterator used for data simulation.

        # Pass when enable is off
        while(self.enableChk == False):
            
            if(self.enableVar == False):
                break
            sleep(0.05)
            self.newData.emit(1, dfco[i])
            i = i+1

        # Loop for reading sensor responses
        while(self.enableChk == True):
            if(self.enableVar == False):
                break
            

            # This block waits for serial response for data emission. For read errors
            try:
                newItem = int(re.findall('\d+', self.coCon.readline().decode())[1]) * 10    # Index can be changed to 0 for the device filtered value or 1 for the (faster) raw output.
                self.newData.emit(1, newItem)
                self.oldData.append(newItem)
                self.coCon.reset_input_buffer() # Buffer needs to be reset fairly often to prevent buffer delay.

            # Report failure and add a zero reading for post-processing cleanup. Sleep to allow meter to catchup in case of device lag.
            except:
                print("Failure to read CO2 meter")
                try:
                    self.newData.emit(1, self.oldData[-1])
                except:
                    print(self.oldData)
                self.coCon.reset_input_buffer()
                sleep(0.05)

        print("CO2 meter thread finished.")    
        self.finished.emit()



### Class for setting up the main window.
### This holds most operational functions. 
### Holds the main thread and update loop
### Plots are defined here instead of an additional class for faster performance and thread safety.
class MainUI(QMainWindow):

  
    # Setup information and initializations
    def __init__(self, parent=None):
        super().__init__(parent)

        # Class Variables
        now = datetime.now()                                    # Initial datetime reference
        xTime = now.timestamp()                                 # Timestamp conversion of datetime reference
        self.saveName = 'SaveLog.csv'                           # Default save name for output file (stored in operating folder)
        self.currentVal = 0.000                                 # Container value for last total volume measurement.
        self.currentCoVal = 0.000                               # Container value for last total volume CO2 calculation.
        self.percPkVal = 0.000                                  # Container value for peak CO2 %.
        self.currentVeVco2 = 0.0                                # Container value for ve/vco2 calculation
        self.flowX = collections.deque([xTime], 500)            # Deque holding X datetime values for flow meter readings. Size may be changed by user in setDataPts and will be re-initialized.
        self.flowY = collections.deque([0], 500)                # Deque holding y slpm values for flow meter readings. Size may be changed by user in setDataPts and will be re-initialized.
        self.coX = collections.deque([xTime], 500)              # Deque holding X datetime values for co2 meter readings. Size may be changed by user in setDataPts and will be re-initialized.
        self.coY = collections.deque([0], 500)                  # Deque holding y ppm values for co2 meter readings. Size may be changed by user in setDataPts and will be re-initialized.
        self.integX = collections.deque([xTime], 500)           # Deque holding X datetime values for integrated flow meter readings. Size may be changed by user in setDataPts and will be re-initialized.
        self.integY = collections.deque([0], 500)               # Deque holding y integrated flow values. Size may be changed by user in setDataPts and will be re-initialized.
        self.veVco2X = collections.deque([xTime], 500)          # Deque holding x datetime values for ve/Vco2 calculations
        self.veVco2Y = collections.deque([0], 500)              # Deque holding y values for ve/Vco2 calculations
        self.floTrig = 10.0                                      # Value for trigger level of flow integration in SLPM
        self.coTrig = 20000.0                                   # Value for trigger level of co2 integration in ppm
        self.integratedCo =  0.0                            # Value for holding the total integrated value of co2 over the test
        self.integratedCoPts = 0                                # Value for holding the number of points integrated
        self.integratedCoTime = collections.deque([now, now], 5)
        self.veVco2Val = collections.deque([0],500)                                # Value for holding the value 
        self.maxCo2Val = 0.0                                    # Maximum CO2 value read per session.
        self.maxCo2ValLast = 0.0
        self.volBreathsQ = collections.deque([], 100)               # Deque for holding volume of each breath average is displayed
        self.curVol = collections.deque([0], 500)                                      # Variable holding current breath volume
        self.startVolTime = datetime.now()                                    # Initial datetime reference
        self.stopVolTime = datetime.now()                                    # Initial datetime reference
        self.volFlag = False
        self.coFlag = False

        # Plot initialization
        self.graphWindow = pg.GraphicsWindow()
        self.graphWindow.setMinimumSize(400,400)
        self.setupPlot()

        # Tab display initialization
        self.tabs = QTabWidget()
        self.setupTabs()

        # Save file initialization
        self.setupSave()


        # UI elements Initialization
        # arrangement and display are performed here
        self.setupUi()


    # Function for initializing multi-tab information container
    # Does not create tabs themselves.
    def setupTabs(self):
        
        # Use member QTab object member functions to alter display settings
        self.tabs.setTabPosition(QTabWidget.West)                           # Set tab indicators to left side of screen
        
        # Setup size policy for managing container display size
        # Square stretch sizes are ideal for performance. If altered, tab label sizes will also need to change.
        sizePolicy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        self.tabs.setSizePolicy(sizePolicy)

        # Set up a groupbox inside the second tab to recieve tab details
        # Needed as directly placing the display will alter size on some screen dimensions.
        self.tabAvg = QGroupBox()
        self.setupTab(self.tabAvg)
        self.tabs.addTab(self.tabAvg, "")

        # Set up a groupbox inside the first tab to recieve tab details
        # Needed as directly placing the display will alter size on some screen dimensions.
        self.tabCur = QGroupBox()
        self.setupTab(self.tabCur)
        self.tabs.addTab(self.tabCur, "")

        # Apply titles to tabs. Leave window title blank or it will alter size.
        self.setWindowTitle("")
        self.tabs.setTabText(self.tabs.indexOf(self.tabCur), "Last Breath Est")
        self.tabs.setTabText(self.tabs.indexOf(self.tabAvg), "Average")
    
    
    # Function for initializing the information display contianed in the information tabs.
    # Shows Vol Air, Vol CO2, VE/VCO2, and peak % CO2 as labels
    def setupTab(self, QGroup):
        
        # Use sizepolicy to set display sizes.
        # 0 stretch is used to completely fill container.
        sizePolicy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        QGroup.setSizePolicy(sizePolicy)

        # Use member functions to alter style
        QGroup.setStyleSheet("background-color: rgb(0, 0, 0); border:none")                 # 0, 0, 0, sets background to black.
        QGroup.setMinimumSize(QSize(250, 150))                                              # Set minimum display size. Tuned to minimum font sizes. Smaller values may distort image.

        # Apply a grid layout for organization.
        QGroup.gridLayout = QGridLayout(QGroup)

        # Label to contain title for tab.
        # Top left position
        QGroup.label_title = QLabel(QGroup)
        QGroup.label_title.setStyleSheet("color: rgb(255, 255, 255);")                      # Set text color to white.
        QGroup.gridLayout.addWidget(QGroup.label_title, 0, 0, 1, 1)                         # Add to grid in top left position [x , y , x stretch, y stretch]

        # Label to contain volume information.
        # Takes self.currentVal as a variable to convert to a display string.
        # Number format i.i number of displayed digits is NOT altered.
        QGroup.label_vol = QLabel(QGroup)
        font = QtGui.QFont()
        font.setPointSize(20)                                                               # Font size to be used. 20 is minimum for "at-a-glance" readability.
        QGroup.label_vol.setFont(font)
        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)              # Use size policy to control grid placement intended for 2-3
        sizePolicy.setHorizontalStretch(2)
        sizePolicy.setVerticalStretch(3)
        QGroup.label_vol.setSizePolicy(sizePolicy)
        QGroup.label_vol.setStyleSheet("color: rgb(255, 255, 255);")                        # Set text color to white.
        QGroup.label_vol.setAlignment(Qt.AlignCenter)                                       # Align to center of cell. Better for alignment of rapidly changing numbers.
        QGroup.gridLayout.addWidget(QGroup.label_vol, 2, 0, 1, 1)                           # Add to grid in top middle position [x , y , x stretch, y stretch]

        # Setup label to display ve/vco2 information
        # Takes use 0 for inital value, and vol / vol CO2 for all nonzero Co2 readings.
        QGroup.label_veVc = QLabel(QGroup)
        font = QtGui.QFont()
        font.setPointSize(34)                                                               # Font size to be used. 12 is used to appear smaller than volume readouts. 12 is minimum for readability.
        QGroup.label_veVc.setFont(font)
        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)                                                  # Set 0 stretch to fill line.
        sizePolicy.setVerticalStretch(1)
        QGroup.label_veVc.setSizePolicy(sizePolicy)
        QGroup.label_veVc.setStyleSheet("color: rgb(255, 255, 255);")                       # Set text color to white.
        QGroup.label_veVc.setAlignment(Qt.AlignCenter)                                      # Align to center of cell. Better for alignment of rapidly changing numbers.
        QGroup.gridLayout.addWidget(QGroup.label_veVc, 1, 0, 1, 1)                          # Add to grid in 3rd middle position [x , y , x stretch, y stretch]

        # Setup Label to display peak CO2 % information
        # Takes self.perkPkVal as a variable to convert to a display string.
        # number format is NOT altered. Assumes a percentage conversion.
        QGroup.label_percPk = QLabel(QGroup)
        font = QtGui.QFont()
        font.setPointSize(20)                                                               # Font size to be used. 12 is used to appear smaller than volume readouts. 12 is minimum for readability.
        QGroup.label_percPk.setFont(font)
        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(1)                                                    # Use 0 horizontal stretch to fill line
        QGroup.label_percPk.setSizePolicy(sizePolicy)
        QGroup.label_percPk.setStyleSheet("color: rgb(255, 255, 255);")                     # Set text color to white. 
        QGroup.label_percPk.setAlignment(Qt.AlignCenter)                                    # Align to center of cell. Better for rapidly changing numbers.
        QGroup.gridLayout.addWidget(QGroup.label_percPk, 3, 0, 1, 1)                        # Add to grid in 4th middle position [x , y , x stretch, y stretch]

        # Set the text strings to be initially displayed
        QGroup.label_title.setText("Calculated Breath Information")
        QGroup.label_vol.setText("{} L Air".format(self.currentVal))
        QGroup.label_veVc.setText("{} VE/VCO2".format(self.currentVeVco2))
        QGroup.label_percPk.setText("{} % Peak CO2".format(self.percPkVal))


    # Function for initializing save file
    # Uses self.saveName as filename. MUST have .csv and no special characters.
    # Will append to duplicate file names or create files that do not exist.
    # Only checks current directory and specified subfile 
    def setupSave(self):

        # Boolean, true if the file exists with this exact name in the current directory
        file_exists = os.path.isfile(self.saveName)

        # If the file does not exist, create a new one.
        if (not file_exists or self.saveName == 'SaveLog.csv'):
            with open(self.saveName, 'w', newline='') as csvfile:                                                       # 'w' for write mode.
                cwriter = csv.writer(csvfile, delimiter=',',                                                            # Use comma seperation for compatability with excel and sheets.
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)
                cwriter.writerow(["Datetime1","Flow SLPM","Datetime2","CO2 ppm","Datetime3","VE","Datetime3","VE over VCO2", "Datetime4","CO2Peak"])   # Use this to control formatting and column names.
        
        # If the file exists, set the file to append mode.
        else :
            with open(self.saveName, 'a', newline='') as csvfile:                                                       # 'a' for append mode.
                cwriter = csv.writer(csvfile, delimiter=',',                                                            # Use comma seperation for compatability with excel and sheets.
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)


    # Function for setting up the real-time plot pg object
    def setupPlot(self):

        # Use pg functions to set colors
        pg.setConfigOption('background', 'k')   # 'k' for black
        pg.setConfigOption('foreground', 'w')   # 'w' for white

        # Create, arrange, and label plots.
        # HTML basic can be used to format labels.
        # Timeaxis items used here.
        p1 = self.graphWindow.addPlot(0,0,1,3,labels =  {'left':'<p style="color:cyan;">Breath Flow (SLPM)</p>'},axisItems = {'bottom' : TimeAxisItem(orientation='bottom')})
        p2 = self.graphWindow.addPlot(1,0,1,3,labels =  {'left':'<p style="color:magenta;">CO2 Percent (ppm)</p>'},axisItems = {'bottom' : TimeAxisItem(orientation='bottom')})
        p3 = self.graphWindow.addPlot(2,0,1,3,labels =  {'left':'<p style="color:red;">VE/VCO2</p>'},axisItems = {'bottom' : TimeAxisItem(orientation='bottom')}) #TODO re-link p3
        p4 = self.graphWindow.addPlot(3,0,1,3,labels =  {'left':'<p style="color:cyan;">Avg Breath Volume (L)<br> </p>'},axisItems = {'bottom' : TimeAxisItem(orientation='bottom')})
        
        # Manually set the size of each axis(in pixels).
        # Vertical axis has been commented out. Possibly needed for some displays.
        p1.getAxis('left').setWidth(50)
        #p1.getAxis('left').setHeight(90)
        p2.getAxis('left').setWidth(50)
        #p2.getAxis('left').setHeight(90)
        p3.getAxis('left').setWidth(50)
        #p3.getAxis('left').setHeight(90)
        p4.getAxis('left').setWidth(50)
        #p4.getAxis('left').setHeight(90)

        # Link all axis scrolling to the 1st plot(flow meter readings).
        p2.setXLink(p1)
        p3.setXLink(p1)
        p4.setXLink(p1)

        # Create curves for plotting and set colors
        self.graphWindow.curve1 = p1.plot(pen=('c'))
        self.graphWindow.curve2 = p2.plot(pen=('m'))
        self.graphWindow.curve3 = p3.plot(pen=('r'))
        self.graphWindow.curve4 = p4.plot(pen=('c'))
        
        # Apply data to the curves
        # Curves are empty before this point.
        # This will que each curve for update.
        self.graphWindow.curve1.setData(self.flowX, self.flowY)
        self.graphWindow.curve2.setData(self.coX, self.coY)
        self.graphWindow.curve3.setData(self.veVco2X, self.veVco2Y)
        self.graphWindow.curve4.setData(self.integX, self.integY)


# Function for setting up the majority of the user interface objects. 
    def setupUi(self):

        # Set defaulkt size policy info.
        sizePolicy = QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        sizePolicy.setHorizontalStretch(18)
        sizePolicy.setVerticalStretch(10)

        # Set overall window settings.
        self.setWindowTitle("Breath Sensor v10.2")                                         # Name to appear in toolbar
        self.resize(300, 150)                                                               # Default size (only used when not initialized in fullscreen)
        
        # Create a central widget and apply it to the ui object.
        self.centralWidget = QWidget()
        self.setCentralWidget(self.centralWidget)

        # Create integrator widget
        self.groupBox_integrator = QGroupBox("Integrator Controls (SLPM)")                  # Use a string to set the name of the box.
        self.label_risingTriggerLevel = QLabel("Trigger Level:")
        self.lineEdit_risingTriggerLevel = QLineEdit()
        self.lineEdit_risingTriggerLevel.setText(str(self.floTrig))                # Display Default Value.
        self.pushbutton_integUpdate = QPushButton("Update")
        font = QtGui.QFont()
        font.setPointSize(14)                                                               # Font size to be used. 20 is minimum for "at-a-glance" readability.
        self.groupBox_integrator.setFont(font)
        self.groupBox_integrator_layout = QGridLayout()
        self.groupBox_integrator_layout.addWidget(self.label_risingTriggerLevel, 0,0)
        self.groupBox_integrator_layout.addWidget(self.lineEdit_risingTriggerLevel, 0,1)
        self.groupBox_integrator_layout.addWidget(self.pushbutton_integUpdate, 2,1)
        self.groupBox_integrator.setLayout(self.groupBox_integrator_layout)
        self.groupBox_integrator.setSizePolicy(sizePolicy)
        self.pushbutton_integUpdate.clicked.connect(self.setIntegPts)                       # Connect update button to setIntegPts function.

        #Create Reset Widget
        self.groupBox_reset = QGroupBox("Reset")                  # Use a string to set the name of the box.
        self.label_reset = QLabel("RESET AVERAGE:")
        self.label_resetmt = QLabel("")
        self.label_reset.setStyleSheet("color: red;")
        self.pushbutton_reset = QPushButton("RESET")
        font = QtGui.QFont()
        font.setPointSize(14)                                                               # Font size to be used. 20 is minimum for "at-a-glance" readability.
        self.groupBox_reset.setFont(font)
        self.groupBox_reset_layout = QGridLayout()
        self.groupBox_reset_layout.addWidget(self.label_reset, 0,0)
        self.groupBox_reset_layout.addWidget(self.pushbutton_reset, 1,0)
        self.groupBox_reset_layout.addWidget(self.label_resetmt, 2, 0)
        self.groupBox_reset.setLayout(self.groupBox_reset_layout)
        self.groupBox_reset.setSizePolicy(sizePolicy)
        self.pushbutton_reset.clicked.connect(self.resetAvg)

        # Create CO2 Integrator widget
        self.groupBox_coIntegrator = QGroupBox("Integrator Controls (Co2 ppm)")             # Use string to label the box.
        self.label_coRisingTriggerLevel = QLabel("Trigger Level:")
        self.lineEdit_coRisingTriggerLevel = QLineEdit()
        self.lineEdit_coRisingTriggerLevel.setText(str(self.coTrig))           # Display default value.
        self.pushbutton_coIntegUpdate = QPushButton("Update")
        font = QtGui.QFont()
        font.setPointSize(14)                                                               # Font size to be used. 20 is minimum for "at-a-glance" readability.
        self.groupBox_coIntegrator.setFont(font)
        self.groupBox_coIntegrator_layout = QGridLayout()
        self.groupBox_coIntegrator_layout.addWidget(self.label_coRisingTriggerLevel, 0,0)
        self.groupBox_coIntegrator_layout.addWidget(self.lineEdit_coRisingTriggerLevel, 0,1)
        self.groupBox_coIntegrator_layout.addWidget(self.pushbutton_coIntegUpdate, 2,1)
        self.groupBox_coIntegrator.setLayout(self.groupBox_coIntegrator_layout)
        self.groupBox_coIntegrator.setSizePolicy(sizePolicy)
        self.pushbutton_coIntegUpdate.clicked.connect(self.setCoIntegPts)                   # Connect update button to setCoIntegPts function.

        # Create widget for datapoint management
        self.groupBox_dataPoints = QGroupBox("Data Settings")
        self.label_dataPts = QLabel("Data Points:")
        self.lineEdit_dataPts = QLineEdit()
        self.lineEdit_dataPts.setText("500")                                                # Change to default length of deque used.
        self.pushbutton_dataUpdate = QPushButton("Update")
        font = QtGui.QFont()
        font.setPointSize(14)                                                               # Font size to be used. 20 is minimum for "at-a-glance" readability.
        self.groupBox_dataPoints.setFont(font)
        self.groupBox_dataPoints_layout = QGridLayout()
        self.groupBox_dataPoints_layout.addWidget(self.label_dataPts, 0,0)
        self.groupBox_dataPoints_layout.addWidget(self.lineEdit_dataPts, 0,1)
        self.groupBox_dataPoints_layout.addWidget(self.pushbutton_dataUpdate, 1,1)
        self.groupBox_dataPoints.setLayout(self.groupBox_dataPoints_layout)
        self.groupBox_dataPoints.setSizePolicy(sizePolicy)
        self.pushbutton_dataUpdate.clicked.connect(self.setDataPts)                         # Connect update button to setDataPts function.

        # Create widget for managing flow meter connection
        self.groupBox_flow = QGroupBox("FlowMeter Settings")
        self.label_flowIP = QLabel("Device IP:")
        self.lineEdit_flowIP = QLineEdit()
        self.lineEdit_flowIP.setText("169.254.25.25")                                               # Can be changed to default ip. This was most common in testing.
        self.label_flowPort = QLabel("Device Port:")
        self.lineEdit_flowPort = QLineEdit()
        self.lineEdit_flowPort.setText("3607")                                                      # This is the default port used by the tsi 5300. Should not be changed.
        self.buttonBox_flowEnable = QDialogButtonBox()
        self.buttonBox_flowEnable.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)   # DO NOT change this. Change label names instead.
        self.buttonBox_flowEnable.button(QDialogButtonBox.Cancel).setText('Disconnect')             # Button label name.
        self.buttonBox_flowEnable.button(QDialogButtonBox.Ok).setText('Connect')                    # Button label name.
        font = QtGui.QFont()
        font.setPointSize(10)                                                               # Font size to be used. 20 is minimum for "at-a-glance" readability.
        self.groupBox_flow.setFont(font)
        self.groupBox_flow_layout = QGridLayout()
        self.groupBox_flow_layout.addWidget(self.label_flowIP, 0,0)
        self.groupBox_flow_layout.addWidget(self.lineEdit_flowIP, 0,1)
        self.groupBox_flow_layout.addWidget(self.label_flowPort, 1,0)
        self.groupBox_flow_layout.addWidget(self.lineEdit_flowPort, 1,1)
        self.groupBox_flow_layout.addWidget(self.buttonBox_flowEnable, 2,1)
        self.groupBox_flow.setLayout(self.groupBox_flow_layout)
        self.groupBox_flow.setSizePolicy(sizePolicy)
        self.buttonBox_flowEnable.accepted.connect(self.runFlowSensor)                              # Connect "Connect" button to the runFlowSensor function.
        self.buttonBox_flowEnable.rejected.connect(self.killFlowSensor)                             # Connect "Disconnect" button to the killFlowSensor function. TODO connect

        # Create widget for managing CO2 meter connection
        self.groupBox_coMeter = QGroupBox("Co2Meter Settings")
        self.label_baudRate = QLabel("Baud Rate:")
        self.lineEdit_baudRate = QLineEdit()
        self.lineEdit_baudRate.setText("9600")                                                      # Default baud rate. Should NOT be changed as this is the rate used for SPRINTIR6S devices.
        self.label_coPort = QLabel("Device Port:")
        self.comboBox_coPort = QComboBox()
        for info in QtSerialPort.QSerialPortInfo.availablePorts():                                  # List all connected ports as a dropdown. Usually only a single connection is found.
            self.comboBox_coPort.addItem(info.portName())
        self.comboBox_coPort.addItem('TEST')
        self.buttonBox_coEnable = QDialogButtonBox()
        self.buttonBox_coEnable.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)     # DO NOT change this. Change button labels instead.
        self.buttonBox_coEnable.button(QDialogButtonBox.Cancel).setText('Disconnect')               # Button label.
        self.buttonBox_coEnable.button(QDialogButtonBox.Ok).setText('Connect')                      # Button label.
        font = QtGui.QFont()
        font.setPointSize(10)                                                               # Font size to be used. 20 is minimum for "at-a-glance" readability.
        self.groupBox_coMeter.setFont(font)
        self.groupBox_co_layout = QGridLayout()
        self.groupBox_co_layout.addWidget(self.label_baudRate, 0,0)
        self.groupBox_co_layout.addWidget(self.lineEdit_baudRate, 0,1)
        self.groupBox_co_layout.addWidget(self.label_coPort, 1,0)
        self.groupBox_co_layout.addWidget(self.comboBox_coPort, 1,1)
        self.groupBox_co_layout.addWidget(self.buttonBox_coEnable, 2,1)
        self.groupBox_coMeter.setLayout(self.groupBox_co_layout)
        self.groupBox_coMeter.setSizePolicy(sizePolicy)
        self.buttonBox_coEnable.accepted.connect(self.runCoSensor)                                  # Connect the "Connect" button to the runCoSensor function
        self.buttonBox_coEnable.rejected.connect(self.killCoSensor)                                 # Connect the "Disconnect" button to the killCoSensor function

        # Create a widget for save file manipulation
        self.groupBox_save = QGroupBox("Data Logging Settings")
        self.label_saveName = QLabel("Save File Name:")
        self.lineEdit_saveName = QLineEdit()
        self.buttonBox_saveEnable = QDialogButtonBox()
        self.buttonBox_saveEnable.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)   # DO NOT change this. Change button labels instead.
        self.buttonBox_saveEnable.button(QDialogButtonBox.Cancel).setText('Stop')
        self.buttonBox_saveEnable.button(QDialogButtonBox.Cancel).setEnabled(False)                 # Disabled by default. Used to indicate current save state. Enabled when actively saving.
        self.buttonBox_saveEnable.button(QDialogButtonBox.Ok).setText('Save')
        font = QtGui.QFont()
        font.setPointSize(14)                                                               # Font size to be used. 20 is minimum for "at-a-glance" readability.
        self.groupBox_save.setFont(font)
        self.groupBox_save_layout = QGridLayout()
        self.groupBox_save_layout.addWidget(self.label_saveName, 0,0)
        self.groupBox_save_layout.addWidget(self.lineEdit_saveName, 0,1)
        self.groupBox_save_layout.addWidget(self.buttonBox_saveEnable, 2,1)
        self.groupBox_save.setLayout(self.groupBox_save_layout)
        self.groupBox_save.setSizePolicy(sizePolicy)
        self.buttonBox_saveEnable.accepted.connect(self.newSave)                                    # Connect the "Save" button with the newSave function
        self.buttonBox_saveEnable.rejected.connect(self.stopSave)                                   # Connect the "Stop" button with the stopSave function
        
        # Apply size policy to graph window
        self.graphWindow.setSizePolicy(sizePolicy)


        # Assign each widget to a grid layout
        layout = QGridLayout()
        layout.addWidget(self.tabs, 0, 0, 4, 4)
        layout.addWidget(self.groupBox_reset, 0, 4, 4, 1)
        layout.addWidget(self.groupBox_coIntegrator, 0, 5, 2, 3)
        layout.addWidget(self.groupBox_dataPoints, 0, 11, 2, 3)
        layout.addWidget(self.groupBox_integrator, 2, 5, 2, 3)
        layout.addWidget(self.groupBox_flow, 0, 8, 2, 3)
        layout.addWidget(self.groupBox_coMeter, 2, 8, 2, 3)
        layout.addWidget(self.groupBox_save, 2, 11, 2, 3)
        layout.addWidget(self.graphWindow, 4, 0, 11, 14)
        self.centralWidget.setLayout(layout)


    def resetAvg(self):
        try:
            now = datetime.now()
            self.integratedCo =  0.0                            # Value for holding the total integrated value of co2 over the test
            self.integratedCoPts = 0                                # Value for holding the number of points integrated
            self.tabAvg.label_veVc.setText("{:0.3f} VE/VCO2".format(0.00))
            self.maxCo2Val = 0
            self.tabAvg.label_percPk.setText("{:0.3f} % Peak CO2".format(self.maxCo2Val))

            self.volBreathsQ = collections.deque([], 100)
            self.tabAvg.label_vol.setText("{:0.3f} L Air".format(0))
            self.volFlag = False
        except:
            print("Could not reset!")
    # Function for changing the save file
    # Uses the user entry for self.linedit_savename as a file name.
    # Can have poor results if file is not named as a standard name.csv.
    # Will append to already existing files.
    def newSave(self):
        
        try:
            # Check if the entered item can be converted to a string.
            # If so, the save name item is changed to the user entry.
            # This does not check for special characters or other poor file naming practices.
            if isinstance(self.lineEdit_saveName.text(), str):
                self.saveName = self.lineEdit_saveName.text()
            
            # Create the file if it does not alrady exist
            file_exists = os.path.isfile(self.saveName)
            if (not file_exists or self.saveName == 'SaveLog.csv'):
                with open(self.saveName, 'w', newline='') as csvfile:
                    cwriter = csv.writer(csvfile, delimiter=',',
                                quotechar='|', quoting=csv.QUOTE_MINIMAL)
                    cwriter.writerow(["Datetime1","Flow SLPM","Datetime2","CO2 ppm","Datetime3","VE","Datetime3","VE over VCO2", "Datetime4","CO2Peak"])
            
            # Append to the file if it does not already exist.
            else :
                with open(self.saveName, 'a', newline='') as csvfile:
                    cwriter = csv.writer(csvfile, delimiter=',',
                                quotechar='|', quoting=csv.QUOTE_MINIMAL)

            #Switch the save button enable states to indicate that the program is currently saving data.
            self.buttonBox_saveEnable.button(QDialogButtonBox.Cancel).setEnabled(True)
            self.buttonBox_saveEnable.button(QDialogButtonBox.Ok).setEnabled(False)

        # Invalid file names or other errors should fall here.
        # No program data will be changed and the state will not change to indicate to the user of the failure.
        except:
            pass


    # Function to stop saving to a particular file
    # Acts to convert saving back to the default save file.
    # Checks for file in case of deletion or error.
    def stopSave(self):
        self.saveName = 'SaveLog.csv'                                                                                   # The default save file name. Change this as well as the variable upon altering.
        
        # Check to see if file has been deleted, corrupted, etc.
        # Will start a new file if needed.
        file_exists = os.path.isfile(self.saveName)
        if (not file_exists or self.saveName == 'SaveLog.csv'):
            with open(self.saveName, 'w', newline='') as csvfile:
                cwriter = csv.writer(csvfile, delimiter=',',
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)
                cwriter.writerow(["Datetime1","Flow SLPM","Datetime2","CO2 ppm","Datetime3","VE","Datetime3","VE over VCO2", "Datetime4","CO2Peak"])
            
        
        # Else continue by appending to the new file.
        # Note this will NOT add any readings collected during the save session to the default file.
        else :
            with open(self.saveName, 'a', newline='') as csvfile:
                cwriter = csv.writer(csvfile, delimiter=',',
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)
        
        # Change the button enable state to indicate that saving to the chosen file is no longer happening.
        self.buttonBox_saveEnable.button(QDialogButtonBox.Cancel).setEnabled(False)
        self.buttonBox_saveEnable.button(QDialogButtonBox.Ok).setEnabled(True)


    # Function for changing the number of points displayed on the graph and/or used to calculate average readings
    # Takes the user input for self.linEdit_dataPts as a value.
    # Will do nothing if the user input cannot be converted to a string.
    # Large user inputs may cause memory issues.
    # Any change will reset the deques and will lose data held inside the program. Graph size will reset. Saved data will not be affected.
    def setDataPts(self):

        # Confirm that user entry is present.
        if (self.lineEdit_dataPts.text() != "" ):
            # Change the user input to the length for each data deque.
            try:
                newVal = int(self.lineEdit_dataPts.text())  # Convert input to integer
                now = datetime.now()                        # Needed to setup timeaxis without significant data offset
                xTime = now.timestamp()

                self.flowX = collections.deque([xTime], newVal)            # Deque holding X datetime values for flow meter readings. Size may be changed by user in setDataPts and will be re-initialized.
                self.flowY = collections.deque([0], newVal)                # Deque holding y slpm values for flow meter readings. Size may be changed by user in setDataPts and will be re-initialized.
                self.coX = collections.deque([xTime], newVal)              # Deque holding X datetime values for co2 meter readings. Size may be changed by user in setDataPts and will be re-initialized.
                self.coY = collections.deque([0], newVal)                  # Deque holding y ppm values for co2 meter readings. Size may be changed by user in setDataPts and will be re-initialized.
                self.integX = collections.deque([xTime], newVal)           # Deque holding X datetime values for integrated flow meter readings. Size may be changed by user in setDataPts and will be re-initialized.
                self.integY = collections.deque([0], newVal)               # Deque holding y integrated flow values. Size may be changed by user in setDataPts and will be re-initialized.
                self.veVco2X = collections.deque([xTime], newVal)          # Deque holding x datetime values for ve/Vco2 calculations
                self.veVco2Y = collections.deque([0], newVal)  
                self.veVco2Val = collections.deque([0],newVal)
        
            # Nothing will change if the user entry fails to convert to an integer.
            except:
                pass
        


    # Function for changing the flow integrator trigger levels
    # Uses user input for self.lineEdit_risingTriggerLevel and self.lineEdit_fallingTriggerLevel.
    # Checks that user input can be converted to float and prints error messages without change if it cannot.
    def setIntegPts(self):

        if (self.lineEdit_risingTriggerLevel.text() != ""):
            # Try to convert the user input to a float and set it as the trigger level.
            try:
                newVal = float(self.lineEdit_risingTriggerLevel.text())
                self.floTrig = newVal

            # If the input cannot be used, inform the user.
            except:
                print("Error: Bad input for Flow Meter Rising Trigger Level.")



    # Function for changing the CO2 integrator trigger levels
    # Uses user input for self.lineEdit_coRisingTriggerLevel and self.lineEdit_coFallingTriggerLevel.
    # Checks that user input can be converted to float and prints error messages without change if it cannot.
    def setCoIntegPts(self):

        # Check that user has put something in the input field.
        if (self.lineEdit_coRisingTriggerLevel.text() != ""):
            # Try to convert the user input to a float and set it as the trigger level.
            try:
                newVal = float(self.lineEdit_coRisingTriggerLevel.text())
                self.coTrig = newVal
            
            # If the input cannopt be used, inform the user.
            except:
                print("Error: Bad input for CO2 Rising Trigger Level.")
        

    # Function for starting the CO2 meter connection and thread
    # Set serial connection based on user input values or defautl entries.
    # Starts new thread, even on connection failure.
    # Does NOT check user input. May cause problems with strange inputs.
    def runCoSensor(self):

        # Set up a thread
        self.thread1 = QThread()                    # Create a q thread object
        self.worker1 = CoSensorWorker()             # Create a worker object.
        self.worker1.moveToThread(self.thread1)     # Move the worker to the thread.

        # Try a serial connection
        try:
            self.coCon = serial.Serial(self.comboBox_coPort.currentText(), self.lineEdit_baudRate.text(), timeout=1) #1s timeout saves from bad connection lockout
        except:
            pass
        # Connect signals and slots
        self.thread1.started.connect(self.worker1.run)
        self.worker1.finished.connect(self.thread1.quit)
        self.worker1.finished.connect(self.worker1.deleteLater)
        self.thread1.finished.connect(self.thread1.deleteLater)
        self.worker1.newData.connect(self.dataUpdate)

        # Test sensor connection
        if(self.comboBox_coPort.currentText() != "" and self.lineEdit_baudRate.text() != ""):

            

            #Check for and report connection status
            try:
                if self.coCon.isOpen():
                    print(self.coCon.isOpen())
                    self.worker1.enableChk = True
                    x = self.coCon.readline().decode()      # Store most recent output
                    #self.coCon.write(b'G\r\n')            # Set zero for CO2 meter
                    self.coCon.write(b'A 0\r\n')            # Set digital output smoothing to 0. Higher for more smoothing.
                    sleep(0.5)                              # Sleep to allow device to cath up.
                    self.coCon.reset_input_buffer()         # Clear the serial buffer.
                    self.worker1.connectConn(self.coCon)    # Pass the serial connection into the worker.

            # If device does not respond, inform the user.    
            except:
                print("CO2 Device connection failed")
        
        #Start the thread
        self.thread1.start()



    # Function for stopping the CO2 meter thread
    def killCoSensor(self):
        self.worker1.enableVar = False  # Disable the worker variable to close the loop.
        try:
            self.coCon.close()              # Close the serial connection.
        except:
            print("Could not close serial connection.")



    # Function for starting the flow sensor connection and thread
    # Set socket connection based on user input values or default entries.
    # Starts new thread, even on connection failure.
    # Does NOT check user input. Can cause problems with strange inputs.
    def runFlowSensor(self):

        # Set up a thread
        self.thread = QThread()                                 # Q Thread item.
        self.worker = FlowSensorWorker()                        # Worker object for thread.
        self.worker.moveToThread(self.thread)                   # Move the worker into the thread.

        # Connect signals and slots to otehr functions.
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.newData.connect(self.dataUpdate)

        # Prepare serial connection to flow meter
        # Check for user entry in both fields, skip connection attempt if either is empty.
        if(self.lineEdit_flowIP.text() != "" and self.lineEdit_flowPort.text() != ""):
            # Convert user entry to connection variables.
            self.flowIP = self.lineEdit_flowIP.text()
            self.flowPort = int(self.lineEdit_flowPort.text())

            # Try to establish a socket connection.
            try:
                # Set socket settings and begin connection.
                self.floSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.floSocket.settimeout(1)                                            # Set 1s timeout period in case of bad or frozen connection.
                self.floSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.floSocket.connect((self.flowIP, self.flowPort))
                
                
                # send a break command to clear any previous commands sent across the connection.
                self.floSocket.sendall(b'BREAK\r')
                
                # Try and establish communication with the device.
                try:
                    print(self.floSocket.recv(1024))            # Print response to break command.
                    self.floSocket.sendall(b'SSR0050\r')        # Send command to set sample rate in ms. 50 is ideal to match CO2 meter.
                    print(self.floSocket.recv(1024))            # Print response to ssr command.
                    self.worker.connectConn(self.floSocket)     # Pass valid connection into worker.
                    self.worker.enableChk = True                # Change this to True ONLY when the connection is valid.
                    sleep(0.5)                                  # Wait for a short time in order to let device catch up to settings changes.

                # Report to user if device does not respond to connection.
                except:
                    print("Device connection failed")

            # Report to user if input fails to set up a valid socket connection.
            except:
                print("Failed to set up a socket for connection")

        #Start the thread
        self.thread.start()



    # Function for stopping the flow sensor thread
    def killFlowSensor(self):
        try:
            self.floSocket.sendall(b'BREAK\r')      # Send a break command to the meter to stop readings.
        except:
            print("Could not send device BREAK")
        self.worker.enableVar = False           # Use the worker variable to close the running loop.



# Function for performing UI and calculation updates
    # Used on every sensor update. Takes an index value 'index' to indicate either 0:the flow methods, or 1: the co2 methods
    def dataUpdate(self, index, n): 

        # This section operates the updates relating to the flow meter readings.
        if(index == 0):
            
            flowNow = datetime.now()                        # Fetch current datetime reference
            flowXTime = flowNow.timestamp()             
            
            # Append current time and reading to flow graph deque.
            self.flowX.append(flowXTime)
            self.flowY.append(n)

            # Try to perform integration math.
            try:
                self.integY.append(0) # TODO Replace with real
                self.integX.append(flowXTime)
            # If the integrator fails, the result is expected to be zero.
            # The integrator should give its own error message.
            except:
                self.integX.append(flowXTime)
                self.integY.append(0)

            # Apply the changed data sets as new curves.
            self.graphWindow.curve1.setData(self.flowX, self.flowY)
            self.graphWindow.curve4.setData(self.integX, self.integY)

            # Save the new flow information
            with open(self.saveName, 'a', newline='') as csvfile:
                cwriter = csv.writer(csvfile, delimiter=',',
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)
                cwriter.writerow([flowNow,n,None,None,None,None,None,None,None,None])
            self.volBreath(n)


        # This section operates the data updates relating to co2 meter readings.   
        if(index == 1):

            now = datetime.now()                    # Fetch the current datetime reference.
            xTime = now.timestamp()
            self.coX.append(xTime)                  
            self.coY.append(n)                      # Apply the new reading to the graph data deque.

            # Save the new CO2 reading.
            with open(self.saveName, 'a', newline='') as csvfile:
                cwriter = csv.writer(csvfile, delimiter=',',
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)
                cwriter.writerow([None,None,now,n,None,None,None,None,None,None])
            
            self.veVco2(n)

            self.co2Max(n)
            # Apply the new deques as curve data.
            self.graphWindow.curve2.setData(self.coX, self.coY)
            self.graphWindow.curve3.setData(self.coX, self.veVco2Val)

            

    def veVco2(self, n):
        
        if (n > self.coTrig):
            now = datetime.now()                                    # Initial datetime reference
            self.integratedCoTime.append(now)

            #print((self.integratedCoTime[-1]-self.integratedCoTime[-2]).total_seconds())
            if ((self.integratedCoTime[-1]-self.integratedCoTime[-2]).total_seconds() > 0.06 or (self.integratedCoTime[-1]-self.integratedCoTime[-2]).total_seconds() < 0.04):
                self.integratedCo = self.integratedCo + ((n / 1000000) * 0.05)
            
            else:
                self.integratedCo = self.integratedCo + ((n / 1000000) * (self.integratedCoTime[-1]-self.integratedCoTime[-2]).total_seconds())
            
            self.integratedCoPts = self.integratedCoPts + 1
            self.veVco2Val.append(1/(self.integratedCo/(self.integratedCoPts*.05)))
            self.tabAvg.label_veVc.setText("{:0.3f} VE/VCO2".format(1/(self.integratedCo/(self.integratedCoPts*.05))))
        else:
            self.veVco2Val.append(0)

    def co2Max(self, n):
        pass
    """
        now = datetime.now()
        if(self.coFlag == False):
            if(n >= self.coTrig):
                self.maxCo2ValLast = n
                self.volFlag = True
            
            else:
                pass

        if(self.volFlag == True):
            if(n >= self.coTrig):
                self.curVol.append(n*(5/6000))
            
            else:
                self.volBreathsQ.append(sum(self.curVol))
                self.tabCur.label_vol.setText("{:0.3f} L Air".format(self.volBreathsQ[-1]))
                # Save the new VE reading.
                with open(self.saveName, 'a', newline='') as csvfile:
                    cwriter = csv.writer(csvfile, delimiter=',',
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)
                    cwriter.writerow([None,None,None,None,now,self.curVol,None,None,None,None])
                self.curVol = collections.deque([], 500)
                
                self.tabAvg.label_vol.setText("{:0.3f} L Air".format(sum(self.volBreathsQ)/len(self.volBreathsQ)))
                self.volFlag = False


        if (n > self.maxCo2Val):
            self.maxCo2Val = n
            self.tabAvg.label_percPk.setText("{:0.3f} % Peak CO2".format(self.maxCo2Val/10000))

        return
    """

    def volBreath(self, n):
        now = datetime.now()
        volNow = now.timestamp()
        if(self.volFlag == False):
            if(n >= self.floTrig):
                self.curVol.append(n*(5/6000))
                self.volFlag = True
            
            else:
                pass

        if(self.volFlag == True):
            if(n >= self.floTrig):
                self.curVol.append(n*(5/6000))
            
            else:
                self.volBreathsQ.append(sum(self.curVol))
                self.tabCur.label_vol.setText("{:0.3f} L Air".format(self.volBreathsQ[-1]))
                # Save the new VE reading.
                with open(self.saveName, 'a', newline='') as csvfile:
                    cwriter = csv.writer(csvfile, delimiter=',',
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)
                    cwriter.writerow([None,None,None,None,volNow,self.volBreathsQ[-1],None,None,None,None])
                self.curVol = collections.deque([], 500)
                
                self.tabAvg.label_vol.setText("{:0.3f} L Air".format(sum(self.volBreathsQ)/len(self.volBreathsQ)))
                self.volFlag = False


# Initial setup and function calls needed for operation
app = QApplication(sys.argv)    # Create an object for Qt.
win = MainUI()                  # Create a UI class object.
win.showMaximized()             # Show the UI object in full screen.
sys.exit(app.exec())            # Exit the program on window exit.
