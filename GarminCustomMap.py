# -*- coding: utf-8 -*-
"""
/***************************************************************************
 GarminCustomMap
                                 A QGIS plugin
 Export the map canvas to a Garmin Custom Map (.kmz-file)
                              -------------------
        begin                : 2015-09-06
        git sha              : $Format:%H$
        copyright            : (C) 2015 by Stefan Blumentrath - Norwegian Institute for Nature Research (NINA)
        email                : stefan.blumentrath@nina.no
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from qgis.core import *
from qgis.gui import *
from qgis.utils import *

from osgeo import gdal
from osgeo import gdalnumeric
from osgeo import gdalconst
from osgeo import osr

import sys
import itertools
import os
import subprocess
import zipfile
import zlib
import tempfile

from math import *

# Initialize Qt resources from file resources.py
from GarminCustomMaps import resources
# Import the code for the dialog
from .GarminCustomMap_dialog import GarminCustomMapDialog
import os.path
from PyQt5.QtWidgets import QAction, QFileDialog, QDialog, QMessageBox, QProgressBar


class GarminCustomMap:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'GarminCustomMap_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Create the dialog (after translation) and keep reference
        self.dlg = GarminCustomMapDialog()

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&GarminCustomMap')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'GarminCustomMap')
        self.toolbar.setObjectName(u'GarminCustomMap')

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('GarminCustomMap', message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/GarminCustomMap/gcm_icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Create Garmin Custom Map from map canvas'),
            callback=self.run,
            parent=self.iface.mainWindow())

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&GarminCustomMap'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    def cleanUp(self):
        # Reset mapSettings
        mapSettings.setOutputSize(QSize(old_width, old_height), old_dpi)

        if os.path.exists(out_put + ".png") :
            os.remove(out_put + ".png")

        if os.path.exists(out_put + ".png.aux.xml") :
            os.remove(out_put + ".png.aux.xml")

        if os.path.exists(output_geofile) :
            os.remove(output_geofile)

        if os.path.exists(os.path.join(out_folder, input_geofile)) :
            os.remove(os.path.join(out_folder, input_geofile))

        if os.path.exists(os.path.join(out_folder, 'doc.kml')) :
            os.remove(os.path.join(out_folder, 'doc.kml'))

        if os.path.exists(os.path.join(out_folder, t_name)) :
            os.remove(os.path.join(out_folder, t_name))

        if os.path.exists(out_folder) :
            os.rmdir(out_folder)

    def run(self):
        """Run method that performs all the real work"""
        # prepare dialog parameters
        settings = QSettings()
        lastDir = settings.value("/UI/lastShapefileDir")
        filter = "GarminCustomMap-files (*.kmz)"
        out_putFile = QgsEncodingFileDialog(None, "Select output file", 'My_CustomMap.kmz', "GarminCustomMap (*.kmz)")
        out_putFile.setDefaultSuffix("kmz")
        out_putFile.setFileMode(QFileDialog.AnyFile)
        out_putFile.setAcceptMode(QFileDialog.AcceptSave)
        # out_putFile.setConfirmOverwrite(True)
        if out_putFile.exec_() == QDialog.Accepted:
            kmz_file = out_putFile.selectedFiles()[0]
            # Get mapCanvas and mapRenderer variables
            canvas = self.iface.mapCanvas()
            scale = canvas.scale()
            mapSettings = canvas.mapSettings()
            mapRect = canvas.extent()
            width = int(round(mapSettings.outputSize().width()))
            height = int(round(mapSettings.outputSize().height()))
            srs = mapSettings.destinationCrs()
            SourceCRS = str(srs.authid())
            # Save settings for resetting the mapRenderer after GCM production
            old_width = mapSettings.outputSize().width()
            old_height = mapSettings.outputSize().height()
            old_dpi = mapSettings.outputDpi()
            # Give information about project projection, mapCanvas size and Custom map settings
            if (height * width) % (1024.0 * 1024.0) >= 1:
                expected_tile_n_unzoomed = int((height * width) / (1024.0 * 1024.0)) + 1
            else:
                expected_tile_n_unzoomed = int((height * width) / (1024.0 * 1024.0))

            if len(str(int(sqrt(100 / ((height * width) / (1024.0 * 1024.0)))))) == 1:
                max_zoom_100 = str(sqrt(100 / ((height * width) / (1024.0 * 1024.0))))[0:3]
            else:
                max_zoom_100 = str(sqrt(100 / ((height * width) / (1024.0 * 1024.0))))[0:4]

            if len(str(int(sqrt(500 / ((height * width) / (1024.0 * 1024.0)))))) == 1:
                max_zoom_500 = str(sqrt(500 / ((height * width) / (1024.0 * 1024.0))))[0:3]
            else:
                max_zoom_500 = str(sqrt(500 / ((height * width) / (1024.0 * 1024.0))))[0:4]

            if SourceCRS != 'EPSG:4326':
                def projWaring():
                    proj_msg = QMessageBox()
                    proj_msg.setWindowTitle("Coordinate Reference System mismatch")
                    proj_msg.setText("The coordinate reference system (CRS) of your project differs from WGS84 (EPSG: 4326). "
                    "It is likely, that you will produce a better Custom Map "
                    "when your project and data has CRS WGS84!\n"
                    "\n"
                    "The number of rows and columns in the exported image "
                    "will be affected by reprojecting to WGS84 and estimates for "
                    "the number of tiles etc. in the \"Setting hints\"-Tab will be incorrect!")
                    proj_msg.exec_()

                widget = iface.messageBar().createMessage("WARNING", "Project CRS differs from WGS84 (EPSG: 4326)")
                button = QPushButton(widget)
                button.setText("Info")
                button.pressed.connect(projWaring)
                widget.layout().addWidget(button)
                iface.messageBar().pushWidget(widget, Qgis.Critical, duration=10)

            # create the dialog
            dlg = GarminCustomMapDialog()

            # Update the dialog
            dlg.textBrowser.setHtml("<p>The following information should help you "
            "to adjust the settings for your Garmin Custom Map.</p>"
            "<p>Your current map canvas contains<br>" + str(height) + " rows and<br>" + str(width) + " colums.</p>"
            "<p>Zooming level 1.0 (map scale of the current map canvas which is 1:" + str(round(scale)) + ") will result in " + str(expected_tile_n_unzoomed) + " tile(s) "
            "(single images within your Garmin Custom Map).</p>"
            "<p>In general, Garmin Custom Maps are limited to a number of 100 tiles in total (across all Garmin Custom Maps on the device). "
            "A Garmin Custom Map produced with the current Zoom level will occupy " + str(expected_tile_n_unzoomed) + "% "
            "of the total capacity of most types of Garmin GPS units.<br>"
            "To comply with a limit of 100 tiles, you should use a zoom factor &lt;= " + max_zoom_100 + ". "
            "This will result in a scale of your Garmin Custom Map of 1 : " + str(int(round(scale / float(max_zoom_100)))) + ".</p>"
            "<p>However, newer Garmin GPS units (Montana, Oregon 6x0, and GPSMAP 64) have a limit of 500 tiles in total (across all Garmin Custom Maps on the device. "
            "For such GPS units, a Garmin Custom Map produced with the current Zoom level will occupy" + str(round((expected_tile_n_unzoomed / 5.0), 1)) + "% "
            "of the maximum possible number of tiles across all Custom Maps on your GPS unit.<br>"
            "To comply with a limit of 500 tiles, you should use a zoom factor &lt;= " + max_zoom_500 + ". "
            "This will result in a scale of your Garmin Custom Map of 1 : " + str(int(round(scale / float(max_zoom_500)))) + ".</p>"

            "<p>For more information on size limits and technical details regarding the "
            """Garmin Custom Maps format see \"About-Tab\" and/or <a href="https://forums.garmin.com/showthread.php?t=2646">https://forums.garmin.com/showthread.php?t=2646</a></p> """)

            dlg.zoom_100.setText("Max. zoom for devices with  &lt;= 100 tiles: " + max_zoom_100 + " (1:" + str(int(round(scale / float(max_zoom_100)))) + ")")
            dlg.zoom_500.setText("Max. zoom for devices with  &lt;= 500 tiles: " + max_zoom_500 + " (1:" + str(int(round(scale / float(max_zoom_500)))) + ")")

            # Show the dialog
            dlg.show()
            result = dlg.exec_()
            # See if OK was pressed
            if result == 1:
                # Set variables
                optimize = int(dlg.flag_optimize.isChecked())
                skip_empty = int(dlg.flag_skip_empty.isChecked())
                max_y_ext_general = int(dlg.nrows.value())
                max_x_ext_general = int(dlg.ncols.value())
                qual = int(dlg.jpg_quality.value())
                # Set options for jpg-production
                options = []
                options.append("QUALITY=" + str(qual))
                draworder = dlg.draworder.value()
                zoom = float(dlg.zoom.value())
                in_file = os.path.basename(kmz_file[0:(len(kmz_file) - 4)])
                max_pix = (1024 * 1024)
                # Create tmp-folder
                out_folder = tempfile.mkdtemp('_tmp', 'gcm_')
                out_put = os.path.join(out_folder, in_file)
                input_file = out_put + u'.png'

                tname = in_file
                # Set QGIS objects
                target_dpi = int(round(zoom * mapSettings.outputDpi()))
                # Initialise temporary output image
                x, y = 0, 0
                width = mapSettings.outputSize().width() * zoom
                height = mapSettings.outputSize().height() * zoom
                mapSettings.setOutputSize(QSize(width, height))
                mapSettings.setOutputDpi(target_dpi)
                mapSettings.setExtent(mapRect)
                mapSettings.setFlags(QgsMapSettings.Antialiasing | QgsMapSettings.UseAdvancedEffects | QgsMapSettings.ForceVectorOutput | QgsMapSettings.DrawLabeling)

                # create output image and initialize it
                image = QImage(QSize(width, height), QImage.Format_RGB555)
                image.fill(qRgb(255, 255, 255))

                # adjust map canvas (renderer) to the image size and render
                imagePainter = QPainter(image)
                imagePainter.begin(image)
                mapRenderer = QgsMapRendererCustomPainterJob(mapSettings, imagePainter)
                mapRenderer.start()
                mapRenderer.waitForFinished()
                imagePainter.end()


                # Save the image
                image.save(input_file, "png")

                # Set Geotransform and NoData values
                input_dataset = gdal.Open(input_file)

                # Set Geotransform values
                ULy = mapRect.yMaximum()
                ULx = mapRect.xMinimum()
                LRx = mapRect.xMaximum()
                LRy = mapRect.yMinimum()
                xScale = (LRx - ULx) / width
                yScale = (LRy - ULy) / height
                input_dataset.SetGeoTransform([ULx, xScale, 0, ULy, 0, yScale])

                # Close dataset
                input_dataset = None

                # Reset mapSettings to old size (monitor)
                mapSettings.setOutputSize(QSize(old_width, old_height))

                # Warp the exported image to WGS84 if necessary
                if SourceCRS != 'EPSG:4326':
                    # Define input and output file
                    input_geofile = out_put + "wgs84.tif"
                    output_geofile = os.path.join(out_folder, input_geofile)
                    # Register tif-driver
                    driver = gdal.GetDriverByName("GTiff")
                    driver.Register()
                    # Define input CRS
                    in_CRS = srs.toWkt()
                    # in_CRS = srs.toWkt().encode('UTF-8')
                    # print type(in_CRS)
                    # Define output CRS
                    out_CRS = QgsCoordinateReferenceSystem(4326, QgsCoordinateReferenceSystem.EpsgCrsId).toWkt()
                    # out_CRS = QgsCoordinateReferenceSystem(4326, QgsCoordinateReferenceSystem.EpsgCrsId).toWkt().encode('UTF-8')
                    # print type(out_CRS)
                    # Open input dataset
                    input_dataset = gdal.Open(input_file)

                    # Create VRT
                    reproj_file = gdal.AutoCreateWarpedVRT(input_dataset, in_CRS, out_CRS)
                    reproj_file.GetRasterBand(1).Fill(255)
                    reproj_file.GetRasterBand(2).Fill(255)
                    reproj_file.GetRasterBand(3).Fill(255)

                    # Reproject
                    gdal.ReprojectImage(input_dataset, reproj_file, in_CRS, out_CRS)
                    reproj_attributes = reproj_file.GetGeoTransform()

                    # Update relevant georef variables
                    ULx = reproj_attributes[0]
                    ULy = reproj_attributes[3]
                    xScale = reproj_attributes[1]
                    yScale = reproj_attributes[5]

                    driver = gdal.GetDriverByName("GTiff")
                    warped_input = driver.CreateCopy(output_geofile, reproj_file, 0)

                    input_dataset = None
                    reproj_file = None
                    warped_input = None
                    input_file = output_geofile

                # Calculate tile size and number of tiles
                indataset = gdal.Open(input_file)

                x_extent = indataset.RasterXSize
                y_extent = indataset.RasterYSize
                if optimize == 1 :
                    # Identify length of the short and long side of the map canvas and their relation
                    short_ext = min(x_extent, y_extent)
                    long_ext = max(x_extent, y_extent)
                    s_l_side_relation = 0

                    # Estimate number of tiles in the result
                    if float(x_extent * y_extent) % (1024 * 1024) >= 1:
                        expected_tile_n = int(float(x_extent * y_extent) / (1024 * 1024)) + 1
                    else:
                        expected_tile_n = int(float(x_extent * y_extent) / (1024 * 1024))

                    # Find settings for tiling with:
                    # 1 minimum number of tiles,
                    # 2 a short / long size relation close to 1,
                    # 3 and a minimum numer of pixels in each tile
                    for tc in range(1, expected_tile_n + 1, 1):
                        if expected_tile_n % tc >= 1:
                            continue
                        else:

                            if short_ext % tc >= 1:
                                s_pix = int(short_ext / tc) + 1
                            else:
                                s_pix = int(short_ext / tc)

                            if long_ext % tc >= 1:
                                l_pix = int(long_ext / (expected_tile_n / tc)) + 1
                            else:
                                l_pix = int(long_ext / (expected_tile_n / tc))

                            if (s_pix * l_pix) <= (1024 * 1024):
                                if min((float(s_pix) / float(l_pix)), (float(l_pix) / float(s_pix))) >= s_l_side_relation:
                                    s_l_side_relation = min((float(s_pix) / float(l_pix)), (float(l_pix) / float(s_pix)))
                                    s_pix_opt = s_pix
                                    l_pix_opt = l_pix

                    # Set tile size variable according to optimal setings
                    if short_ext == x_extent:
                        max_x_ext_general = s_pix_opt
                        max_y_ext_general = l_pix_opt
                    else:
                        max_y_ext_general = s_pix_opt
                        max_x_ext_general = l_pix_opt

                # Identify number of rows and columns
                n_cols_rest = x_extent % max_x_ext_general
                n_rows_rest = y_extent % max_y_ext_general
                #
                if n_cols_rest >= 1:
                    n_cols = (x_extent / max_x_ext_general) + 1
                else:
                    n_cols = (x_extent / max_x_ext_general)

                #
                if n_rows_rest >= 1:
                    n_rows = (y_extent / max_y_ext_general) + 1
                else:
                    n_rows = (y_extent / max_y_ext_general)

                # Check if number of tiles is below Garmins limit of 100 tiles (across all custom maps)
                n_tiles = (n_rows * n_cols)
                if n_tiles > 100:
                    iface.messageBar().pushMessage("WARNING", "The number of tiles is likely to exceed Garmins limit of 100 tiles! Not all tiles will be displayed on your GPS unit. Consider reducing your map size (extend or zoom-factor).", level=QgsMessageBar.WARNING, duration=5)

                progressMessageBar = iface.messageBar().createMessage("Producing tiles...")
                progress = QProgressBar()
                progress.setMaximum(n_tiles)
                progress.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                progressMessageBar.layout().addWidget(progress)
                iface.messageBar().pushWidget(progressMessageBar, Qgis.Info)

                # Check if size of tiles is below Garmins limit of 1 megapixel (for each tile)
                n_pix = (max_x_ext_general * max_y_ext_general)

                if n_pix > max_pix:
                    iface.messageBar().pushMessage("WARNING", "The number of pixels in a tile exceeds Garmins limit of 1 megapixel per tile! Images will not be displayed properly.", level=Qgis.Warning, duration=5)

                kmz = zipfile.ZipFile(kmz_file, 'w')
                with open(os.path.join(out_folder, 'doc.kml'), 'w') as kml:

                    # Write kml header
                    kml.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                    kml.write('<kml xmlns="http://www.opengis.net/kml/2.2">\n')
                    kml.write('  <Document>\n')
                    kml.write('    <name>' + tname.encode('UTF-8').decode('utf-8') + '</name>\n')

                    # Produce .jpg tiles using gdal_translate looping through the complete rows and columns (1024x1024 pixel)
                    y_offset = 0
                    x_offset = 0
                    r = 1
                    c = 1
                    n_tiles = 0
                    empty_tiles = 0
                    # Loop through rows
                    for r in range(1, int(n_rows) + 1, 1):
                        # Define maximum Y-extend of tiles
                        if r == (n_rows) and n_rows_rest > 0:
                            max_y_ext = n_rows_rest
                        else:
                            max_y_ext = max_y_ext_general

                        # (Within row-loop) Loop through columns
                        for c in range(1, int(n_cols) + 1, 1):
                            # Define maximum X-extend of tiles
                            if c == int(n_cols) and n_cols_rest > 0:
                                max_x_ext = n_cols_rest
                            else:
                                max_x_ext = max_x_ext_general
                            # Define name for tile-jpg
                            t_name = tname + '_%(r)d_%(c)d.jpg' % {"r": r, "c": c}
                            # Set parameters for "gdal_translate" (JPEG-driver has no Create() (but CreateCopy()) method so first a VRT has to be created band by band
                            # Create VRT dataset for tile
                            mem_driver = gdal.GetDriverByName("MEM")
                            mem_driver.Register()
                            t_file = mem_driver.Create('', max_x_ext, max_y_ext, 3, gdalconst.GDT_Byte)
                            t_band_1 = indataset.GetRasterBand(1).ReadAsArray(x_offset, y_offset, max_x_ext, max_y_ext)
                            t_band_2 = indataset.GetRasterBand(2).ReadAsArray(x_offset, y_offset, max_x_ext, max_y_ext)
                            t_band_3 = indataset.GetRasterBand(3).ReadAsArray(x_offset, y_offset, max_x_ext, max_y_ext)

                            if skip_empty == 1 :
                                if t_band_1.min() == 255 and t_band_2.min() == 255 and t_band_3.min() == 255 :
                                    empty_tiles = empty_tiles + 1

                            t_file.GetRasterBand(1).WriteArray(t_band_1)
                            t_file.GetRasterBand(2).WriteArray(t_band_2)
                            t_file.GetRasterBand(3).WriteArray(t_band_3)
                            t_band_1 = None
                            t_band_2 = None
                            t_band_3 = None

                            # Translate MEM dataset to JPG
                            jpg_driver = gdal.GetDriverByName("JPEG")
                            jpg_driver.Register()
                            jpg_driver.CreateCopy(os.path.join(out_folder, t_name), t_file, options=options)

                            # Close GDAL-datasets
                            t_file = None
                            t_jpg = None
                            # Get bounding box for tile
                            n = ULy + (y_offset * yScale)
                            s = ULy + ((y_offset + max_y_ext) * yScale)
                            e = ULx + ((x_offset + max_x_ext) * xScale)
                            w = ULx + (x_offset * xScale)
                            # Add .jpg to .kmz-file and remove it together with its meta-data afterwards
                            kmz.write(os.path.join(out_folder, t_name), t_name)
                            os.remove(os.path.join(out_folder, t_name))

                            # Write kml-tags for each tile (Name, DrawOrder, JPEG-Reference, GroundOverlay)
                            kml.write('')
                            kml.write('    <GroundOverlay>\n')
                            kml.write('        <name>' + tname.encode('UTF-8').decode('utf-8') + ' Tile ' + str(r) + '_' + str(c) + '</name>\n')  # %{"r":r, "c":c}
                            kml.write('        <drawOrder>' + str(draworder) + '</drawOrder>\n')  # %{"draworder":draworder}
                            kml.write('        <Icon>\n')
                            kml.write('          <href>' + tname.encode('UTF-8').decode('utf-8') + '_' + str(r) + '_' + str(c) + '.jpg</href>\n')  # %{"r":r, "c":c}
                            kml.write('        </Icon>\n')
                            kml.write('        <LatLonBox>\n')
                            kml.write('          <north>' + str(n) + '</north>\n')
                            kml.write('          <south>' + str(s) + '</south>\n')
                            kml.write('          <east>' + str(e) + '</east>\n')
                            kml.write('          <west>' + str(w) + '</west>\n')
                            kml.write('        </LatLonBox>\n')
                            kml.write('    </GroundOverlay>\n')

                            # Calculate new X-offset
                            x_offset = (x_offset + max_x_ext)
                            n_tiles = (n_tiles + 1)
                            # Update progress bar
                            progress.setValue(n_tiles)
                        # Calculate new Y-offset
                        y_offset = (y_offset + max_y_ext)
                        # Reset X-offset
                        x_offset = 0

                    # Write kml footer
                    kml.write('  </Document>\n')
                    kml.write('</kml>\n')
                # Close kml file
                # kml.close()

                # Close GDAL dataset
                indataset = None

                # Remove temporary geo-tif file
                os.remove(out_put + u'.png')
                os.remove(out_put + u'.png.aux.xml')

                # Remove reprojected temporary geo-tif file if necessary
                if SourceCRS != 'EPSG:4326':
                    os.remove(output_geofile)

                # Add .kml to .kmz-file and remove it together with the rest of the temporary files
                kmz.write(os.path.join(out_folder, u'doc.kml'), u'doc.kml')
                os.remove(os.path.join(out_folder, u'doc.kml'))
                kmz.close()
                os.rmdir(out_folder)
                # Clear progressbar
                iface.messageBar().clearWidgets()

                tiles_total = n_tiles - empty_tiles
                # Give success message
                iface.messageBar().pushMessage("Done", "Produced " + str(tiles_total) + " tiles, with " + str(n_rows) + " rows and " + str(int(n_cols)) + " colums.", level=Qgis.Info, duration=5)
