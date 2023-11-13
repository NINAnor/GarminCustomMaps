"""
/***************************************************************************
 GarminCustomMap
                                 A QGIS plugin
 Export the map canvas to a Garmin Custom Map (.kmz-file)
                              -------------------
        begin                : 2015-09-06
        git sha              : $Format:%H$
        copyright            : (C) 2015 by Stefan Blumentrath
                               Norwegian Institute for Nature Research (NINA)
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
import os
import os.path
import tempfile
import time
import zipfile
from io import TextIOWrapper
from math import sqrt

from osgeo import gdal, gdalconst
from osgeo.gdal import Dataset
from PyQt5.QtCore import (QCoreApplication, QSettings, QSize, Qt, QTranslator,
                          qVersion)
from PyQt5.QtGui import QIcon, QImage, QPainter, qRgb
from PyQt5.QtWidgets import (QAction, QDialog, QFileDialog, QMessageBox,
                             QProgressBar, QPushButton)
from qgis.core import (Qgis, QgsCoordinateReferenceSystem,
                       QgsMapRendererCustomPainterJob, QgsMapSettings,
                       QgsMessageLog, QgsRectangle)
from qgis.gui import QgsEncodingFileDialog
from qgis.utils import iface

# Import the code for the dialog
from .GarminCustomMap_dialog import GarminCustomMapDialog
# Load optimization functions
from .optimization import optimize_fac

DIALOG_TEXT = """<span  style=\"font-family='Sans serif'; font-size=11pt; font-weight:400\">
<p>
The following information should help you to adjust the settings for your Garmin Custom Map.
</p>

<p>
Your current map canvas contains:<br>&bull; {height} rows<br>&bull; {width} columns
</p>

<p>
Zooming level 1.0 (map scale of the current map canvas which is 1:{scale})
will result in {expected_tile_n_unzoomed} (single images within your Garmin Custom Map).
</p>

<p>
In general, Garmin Custom Maps are limited to a number of 100 tiles in
total (across all Garmin Custom Maps on the device).
A Garmin Custom Map produced with the current Zoom level will occupy {cap100:.1%}
of the total capacity of most types of Garmin GPS units.
<br>
To comply with a limit of 100 tiles, you should use a zoom factor &lt;= {max_zoom_100!r:.5}
This will result in a scale of your Garmin Custom Map of 1:{scale_zoom_100}.
</p>

<p>
However, newer Garmin GPS units (Montana, Oregon 6x0, and GPSMAP 64)
have a limit of 500 tiles in total (across all Garmin Custom Maps on the device).
For such GPS units, a Garmin Custom Map produced with the current Zoom level will occupy {cap500:.1%}
of the maximum possible number of tiles across all Custom Maps on your GPS unit.
<br>
To comply with a limit of 500 tiles, you should use a zoom factor &lt;= {max_zoom_500!r:.5}
This will result in a scale of your Garmin Custom Map of 1:{scale_zoom_500}.
</p>

<p>
For more information on size limits and technical details regarding the
Garmin Custom Maps format see \"About\" tab and/or
<a href="https://support.garmin.com/en-US/?faq=UcO3cFueS12IwCnizrJjeA">
the official docs</a>
</p></span> """


def dbgMsg(message: str) -> None:
    """Info logMessage convenience function"""
    QgsMessageLog.logMessage(message, "GarminCustomMap", level=Qgis.Info)


def gdal_info_dbg(dataset: Dataset) -> None:
    """Write debug info about input dataset to logMessage"""
    dbgMsg("*--- GDAL info ---*")
    dbgMsg(
        "Driver: {}/{}".format(
            dataset.GetDriver().ShortName,
            dataset.GetDriver().LongName,
        )
    )
    dbgMsg(
        "Size: {} x {} x {}".format(
            dataset.RasterXSize,
            dataset.RasterYSize,
            dataset.RasterCount,
        )
    )
    dbgMsg("Projection: {}".format(dataset.GetGeoTransform()))
    dbgMsg("Geotransform: {}".format(dataset.GetGeoTransform()))
    dbgMsg("-------------------")


def projection_warning(iface: iface):
    """Projection mismatch warning"""
    widget = iface.messageBar().createMessage(
        "WARNING", "Project CRS differs from WGS84 (EPSG: 4326)"
    )
    button = QPushButton(widget)
    button.setText("Info")
    button.pressed.connect(projection_warning_box)
    widget.layout().addWidget(button)
    iface.messageBar().pushWidget(widget, Qgis.Warning, duration=10)


def projection_warning_box():
    """Projection mismatch warning box"""
    proj_msg = QMessageBox()
    proj_msg.setWindowTitle("Coordinate Reference System mismatch")
    proj_msg.setText(
        "The coordinate reference system (CRS) of your project differs from WGS84 (EPSG: 4326). "
        "It is likely, that you will produce a better Custom Map "
        "when your project and data has CRS WGS84!\n"
        "\n"
        "The number of rows and columns in the exported image "
        "will be affected by reprojecting to WGS84 and estimates for "
        'the number of tiles etc. in the "Setting hints"-Tab will be incorrect!'
    )
    proj_msg.exec_()


def tile_to_kmz(
    tile_name: str,
    kmz: zipfile.ZipFile,
    tile_height: int,
    tile_width: int,
    x_offset: int,
    y_offset: int,
    full_extent_dataset: Dataset,
    temp_out_folder: str,
    options: list[str],
) -> None:
    """Produce time and write to the kmz"""
    # Set parameters for "gdal_translate"
    # JPEG-driver has no Create() so we will create an in-memory dataset and then CreateCopy()
    mem_driver = gdal.GetDriverByName("MEM")
    mem_driver.Register()
    tile = mem_driver.Create("", tile_width, tile_height, 3, gdalconst.GDT_Byte)

    # Read a tile size portion of the indataset full extent image
    t_band_1 = full_extent_dataset.GetRasterBand(1).ReadAsArray(
        x_offset, y_offset, tile_width, tile_height
    )
    t_band_2 = full_extent_dataset.GetRasterBand(2).ReadAsArray(
        x_offset, y_offset, tile_width, tile_height
    )
    t_band_3 = full_extent_dataset.GetRasterBand(3).ReadAsArray(
        x_offset, y_offset, tile_width, tile_height
    )

    # Write the tile size portion of the indataset to the tile jpg and close bands
    tile.GetRasterBand(1).WriteArray(t_band_1)
    tile.GetRasterBand(2).WriteArray(t_band_2)
    tile.GetRasterBand(3).WriteArray(t_band_3)
    # Close datasets
    t_band_1 = None
    t_band_2 = None
    t_band_3 = None

    # Translate MEM dataset to JPG
    jpg_driver = gdal.GetDriverByName("JPEG")
    jpg_driver.Register()
    temp_tile_file = os.path.join(temp_out_folder, tile_name)
    jpg_driver.CreateCopy(temp_tile_file, tile, options=options)

    # Close GDAL datasets
    tile = None

    # Add .jpg to .kmz-file and remove it together with its meta-data afterwards
    kmz.write(temp_tile_file, tile_name)
    os.remove(temp_tile_file)


def tile_metadata_to_kml(
    kml: TextIOWrapper,
    N: float,
    S: float,
    E: float,
    W: float,
    r: int,
    c: int,
    output_base_name: str,
    draworder: int,
) -> None:
    # Write kml-tags for each tile (Name, DrawOrder, JPEG-Reference, GroundOverlay)
    kml.write("")
    kml.write("    <GroundOverlay>\n")
    kml.write(
        "        <name>"
        + output_base_name.encode("UTF-8").decode("utf-8")
        + " Tile "
        + str(r)
        + "_"
        + str(c)
        + "</name>\n"
    )  # %{"r":r, "c":c}
    kml.write(
        "        <drawOrder>" + str(draworder) + "</drawOrder>\n"
    )  # %{"draworder":draworder}
    kml.write("        <Icon>\n")
    kml.write(
        "          <href>"
        + output_base_name.encode("UTF-8").decode("utf-8")
        + "_"
        + str(r)
        + "_"
        + str(c)
        + ".jpg</href>\n"
    )  # %{"r":r, "c":c}
    kml.write("        </Icon>\n")
    kml.write("        <LatLonBox>\n")
    kml.write("          <north>" + str(N) + "</north>\n")
    kml.write("          <south>" + str(S) + "</south>\n")
    kml.write("          <east>" + str(E) + "</east>\n")
    kml.write("          <west>" + str(W) + "</west>\n")
    kml.write("        </LatLonBox>\n")
    kml.write("    </GroundOverlay>\n")


def produce_tiles(
    optimize: bool,
    tile_height: int,
    tile_width: int,
    quality: int,
    dbg_flag: bool,
    draworder: int,
    zoom: float,
    kmz_file: str,
    mapSettings: QgsMapSettings,
    mapRect: QgsRectangle,
    srs: QgsCoordinateReferenceSystem,
) -> None:
    """Produce map tiles and write them to file"""
    source_crs_id = str(srs.authid())
    old_width = mapSettings.outputSize().width()
    old_height = mapSettings.outputSize().height()
    # Set variables
    # TODO: add a field to specify max number of tiles
    max_num_tiles = 100
    # Set options for jpg-production
    options = []
    # TODO: add note about image quality to the dialog
    # (values above 95 aren't meaningfully better)
    # https://gdal.org/drivers/raster/jpeg.html#raster-jpeg
    # TODO: add value indicator to UI
    options.append("QUALITY=" + str(quality))
    output_base_name = os.path.splitext(os.path.basename(kmz_file))[0]
    max_pix = 1024 * 1024
    # Create temporary folder for intermediate images
    temp_out_folder = tempfile.mkdtemp("_tmp", "gcm_")
    if dbg_flag:
        dbgMsg(f"Temporary output folder: {temp_out_folder}")
    temp_out_base_path = os.path.join(temp_out_folder, output_base_name)
    full_extent_image = temp_out_base_path + ".png"

    # Set QGIS objects
    round(zoom * mapSettings.outputDpi())
    # Initialise temporary output image
    width = round(mapSettings.outputSize().width() * zoom)
    height = round(mapSettings.outputSize().height() * zoom)
    mapSettings.setOutputSize(QSize(width, height))
    mapSettings.setExtent(mapRect)
    mapSettings.setFlags(
        QgsMapSettings.Flags(
            QgsMapSettings.Antialiasing
            | QgsMapSettings.UseAdvancedEffects
            | QgsMapSettings.ForceVectorOutput
            | QgsMapSettings.DrawLabeling
        )
    )

    # create output image and initialize it
    map_image = QImage(QSize(width, height), QImage.Format_RGB555)
    map_image.fill(qRgb(255, 255, 255))

    # adjust map canvas (renderer) to the image size and render
    imagePainter = QPainter(map_image)
    imagePainter.begin(map_image)
    mapRenderer = QgsMapRendererCustomPainterJob(mapSettings, imagePainter)
    mapRenderer.start()
    mapRenderer.waitForFinished()
    imagePainter.end()

    # Save the image
    # This is the full size image of the whole extent
    # It is temporary because later it gets divided into smaller JPGs
    # TODO: catch exceptions
    if dbg_flag:
        dbgMsg(f"Initial full-extent render file: {full_extent_image}")
    map_image.save(full_extent_image, "png")

    # Set Geotransform and NoData values
    # TODO: catch exceptions
    input_dataset = gdal.Open(full_extent_image)

    # Set Geotransform values
    ULx, ULy = mapRect.xMinimum(), mapRect.yMaximum()
    LRx, LRy = mapRect.xMaximum(), mapRect.yMinimum()
    pixel_width = (LRx - ULx) / width
    pixel_height = (LRy - ULy) / height
    input_dataset.SetGeoTransform([ULx, pixel_width, 0, ULy, 0, pixel_height])

    # Print some GDAL info to messages:
    if dbg_flag:
        gdal_info_dbg(input_dataset)

    # Close dataset
    input_dataset = None

    # Reset mapSettings to old size (monitor)
    mapSettings.setOutputSize(QSize(old_width, old_height))

    # Warp the exported image to WGS84 if necessary
    if source_crs_id != "EPSG:4326":
        # Temporary reprojected full-extent image
        reprojected_full_extent_image = temp_out_base_path + "wgs84.tif"
        # Register geotiff driver
        driver = gdal.GetDriverByName("GTiff")
        driver.Register()
        # Define input CRS
        in_crs = srs.toWkt()
        # Define output CRS
        out_crs = QgsCoordinateReferenceSystem(
            4326, QgsCoordinateReferenceSystem.EpsgCrsId
        ).toWkt()
        # Open input dataset
        input_dataset = gdal.Open(full_extent_image)

        # Create VRT
        reprojected_dataset = gdal.AutoCreateWarpedVRT(input_dataset, in_crs, out_crs)
        reprojected_dataset.GetRasterBand(1).Fill(255)
        reprojected_dataset.GetRasterBand(2).Fill(255)
        reprojected_dataset.GetRasterBand(3).Fill(255)

        # Reproject
        gdal.ReprojectImage(input_dataset, reprojected_dataset, in_crs, out_crs)
        reproj_attributes = reprojected_dataset.GetGeoTransform()

        # Update relevant georef variables
        ULx = reproj_attributes[0]
        ULy = reproj_attributes[3]
        pixel_width = reproj_attributes[1]
        pixel_height = reproj_attributes[5]

        # Write dataset to file
        driver.CreateCopy(reprojected_full_extent_image, reprojected_dataset, 0)

        input_dataset = None
        reprojected_dataset = None

        full_extent_image = reprojected_full_extent_image

    # Here the code breaks up the initial full-extent render file
    # Calculate tile size and number of tiles
    # Add try:catch to make sure we are opening the file properly
    full_extent_dataset = gdal.Open(full_extent_image)
    x_extent = full_extent_dataset.RasterXSize
    y_extent = full_extent_dataset.RasterYSize

    # Print some GDAL info to messages:
    if dbg_flag:
        gdal_info_dbg(full_extent_dataset)

    if optimize:
        if dbg_flag:
            dbgMsg("*--- Optimizing ---*")
        tile_width, tile_height = optimize_fac(
            x_extent, y_extent, max_pix, max_num_tiles
        )
        if (tile_width, tile_height) == (1, 1):
            tile_width, tile_height = 1024, 1024
            if dbg_flag:
                dbgMsg(
                    "Done, couldn't find a good solution with the following constraints:"
                )
                dbgMsg(
                    "Max tile size: {} (1024 x 1024), max number of tiles: {}".format(
                        max_pix, max_num_tiles
                    )
                )
        else:
            tile_width, tile_height = int(tile_width), int(tile_height)
            if dbg_flag:
                dbgMsg(
                    "Done, optimal tile size: {} x {}".format(tile_width, tile_height)
                )
                dbgMsg("-------------------")

    # Calculate number of rows and columns
    n_cols = -(-x_extent // tile_width)
    n_rows = -(-y_extent // tile_height)
    # Calculate number of tiles
    n_tiles = n_rows * n_cols
    # Calculate the pixels that don't fit into the full-tile coverage (trailing pixels)
    x_pix_trailing = x_extent % tile_width
    y_pix_trailing = y_extent % tile_height

    # Check if number of tiles is below Garmins limit of 100 tiles (across all custom maps)
    if n_tiles > 100:
        iface.messageBar().pushMessage(
            "WARNING",
            "The number of tiles ({}) exceeds the Garmin limit of 100 tiles! Not all tiles will be displayed on your GPS unit. Consider reducing your map size (extent or zoom-factor).".format(
                n_tiles
            ),
            level=Qgis.Warning,
            duration=5,
        )

    # Check if size of tiles is below Garmin's limit of 1 megapixel
    if (tile_width * tile_height) > max_pix:
        iface.messageBar().pushMessage(
            "WARNING",
            "The number of pixels in a tile exceeds Garmins limit of 1 megapixel per tile! Images will not be displayed properly.",
            level=Qgis.Warning,
            duration=5,
        )

    progressMessageBar = iface.messageBar().createMessage(
        f"Producing total of {n_tiles} tiles..."
    )
    progress = QProgressBar()
    progress.setMaximum(n_tiles)
    progress.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    progressMessageBar.layout().addWidget(progress)
    iface.messageBar().pushWidget(progressMessageBar, Qgis.Info)

    # Open kmz and kml for writing
    # TODO: Add try:catch to make sure we have permission to write to files
    kmz = zipfile.ZipFile(kmz_file, "w")
    with open(os.path.join(temp_out_folder, "doc.kml"), "w") as kml:
        # Write kml header
        kml.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        kml.write('<kml xmlns="http://www.opengis.net/kml/2.2">\n')
        kml.write("  <Document>\n")
        kml.write(
            "    <name> {} </name>\n".format(
                output_base_name.encode("UTF-8").decode("utf-8")
            )
        )

        # Produce .jpg tiles using gdal_translate looping through the complete rows and columns (1024x1024 pixel)
        y_offset = 0
        x_offset = 0
        tile_width_reset_value = tile_width
        # We reset this to 0 because it's used as the progress indicator in the progress bar
        n_tiles = 0
        # Loop through rows
        for r in range(1, n_rows + 1):
            # If this is the last row, set tile height to trailing pixels
            if r == n_rows and y_pix_trailing > 0:
                tile_height = y_pix_trailing

            # (Within row-loop) Loop through columns
            for c in range(1, n_cols + 1):
                # If this is the last column, set tile width to trailing pixels
                if c == n_cols and x_pix_trailing > 0:
                    tile_width = x_pix_trailing

                # Define name for tile jpg
                tile_name = f"{output_base_name}_{r}_{c}.jpg"
                if dbg_flag:
                    dbgMsg(f"Producing tile: {tile_name}")
                tile_to_kmz(
                    tile_name,
                    kmz,
                    tile_height,
                    tile_width,
                    x_offset,
                    y_offset,
                    full_extent_dataset,
                    temp_out_folder,
                    options,
                )

                # Next we have to populate the KML with metadata
                # Calculate tile extent
                N = ULy + (y_offset * pixel_height)
                S = ULy + ((y_offset + tile_height) * pixel_height)
                E = ULx + ((x_offset + tile_width) * pixel_width)
                W = ULx + (x_offset * pixel_width)
                if dbg_flag:
                    dbgMsg(f"Calculated tile extent: N:{N}, S:{S}, E:{E}, W:{W}")

                tile_metadata_to_kml(kml, N, S, E, W, r, c, output_base_name, draworder)

                # Calculate new X-offset
                x_offset = x_offset + tile_width
                n_tiles = n_tiles + 1
                # Update progress bar
                progress.setValue(n_tiles)
                # Pause between cycles if debugging to get a sense of what's happening
                if dbg_flag:
                    time.sleep(0.25)
                # Output message in status bar, too
                iface.statusBarIface().showMessage(f"Produced tile: {n_tiles}")
            # Calculate new Y-offset
            y_offset = y_offset + tile_height
            # Reset X-offset
            x_offset = 0
            # Reset tile width
            tile_width = tile_width_reset_value

        # Write kml footer
        kml.write("  </Document>\n")
        kml.write("</kml>\n")
        # Exiting this indentaton block exits the kml context and closes the file

    # Close GDAL dataset
    full_extent_dataset = None

    # Remove temporary geo-tif file
    os.remove(temp_out_base_path + ".png")
    os.remove(temp_out_base_path + ".png.aux.xml")

    # Remove reprojected temporary geo-tif file if necessary
    if source_crs_id != "EPSG:4326":
        os.remove(reprojected_full_extent_image)

    # Add .kml to .kmz-file and remove it together with the rest of the temporary files
    kmz.write(os.path.join(temp_out_folder, "doc.kml"), "doc.kml")
    os.remove(os.path.join(temp_out_folder, "doc.kml"))
    kmz.close()
    os.rmdir(temp_out_folder)
    # Clear progressbar
    iface.messageBar().clearWidgets()
    # Clear statusbar
    iface.statusBarIface().clearMessage()
    # Give success message
    tiles_total = n_tiles
    iface.messageBar().pushMessage(
        "Done",
        f"Produced {tiles_total} tiles, with {n_rows} rows and {n_cols} columns.",
        level=Qgis.Success,
        duration=5,
    )


class GarminCustomMap:
    """QGIS Plugin Implementation."""

    def __init__(self, iface: iface):
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
        locale = QSettings().value("locale/userLocale")[0:2]
        locale_path = os.path.join(
            self.plugin_dir, "i18n", f"GarminCustomMap_{locale}.qm"
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > "4.3.3":
                QCoreApplication.installTranslator(self.translator)

        # Create the dialog (after translation) and keep reference
        self.dlg = GarminCustomMapDialog()

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr("&GarminCustomMap")
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar("GarminCustomMap")
        self.toolbar.setObjectName("GarminCustomMap")

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
        return QCoreApplication.translate("GarminCustomMap", message)

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
        parent=None,
    ):
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
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ":/plugins/GarminCustomMap/gcm_icon.png"
        self.add_action(
            icon_path,
            text=self.tr("Create Garmin Custom Map from map canvas"),
            callback=self.run,
            parent=self.iface.mainWindow(),
        )

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(self.tr("&GarminCustomMap"), action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    def run(self):
        """Run method that performs all the real work"""
        # prepare dialog parameters
        settings = QSettings()
        lastDir = settings.value("/UI/lastProjectDir")
        fileFilter = "GarminCustomMap files (*.kmz)"
        # TODO: Getting the file location should be asynchronous and settable
        # in a file field in the UI
        # TODO: This and the actual processing section should be separated out
        # from the run in another refactor, right now the UI is blocked
        output_file_save_dialog = QgsEncodingFileDialog(
            None, "Select output file", lastDir, fileFilter
        )
        output_file_save_dialog.setDefaultSuffix("kmz")
        output_file_save_dialog.setFileMode(QFileDialog.AnyFile)
        output_file_save_dialog.setAcceptMode(QFileDialog.AcceptSave)
        # out_putFile.setConfirmOverwrite(True)

        # Main logic
        if output_file_save_dialog.exec_() == QDialog.Accepted:
            kmz_file = output_file_save_dialog.selectedFiles()[0]
            # Get mapCanvas and mapRenderer variables
            canvas = self.iface.mapCanvas()
            scale = canvas.scale()
            mapSettings = canvas.mapSettings()
            mapRect = canvas.extent()
            srs = mapSettings.destinationCrs()
            SourceCRS = str(srs.authid())
            # Save settings for resetting the mapRenderer after GCM production
            old_width = mapSettings.outputSize().width()
            old_height = mapSettings.outputSize().height()
            mapSettings.outputDpi()
            # Reduce  mapSettings calls: use the existing variables
            width = round(old_width)
            height = round(old_height)
            # Give information about project projection, mapCanvas size and Custom map settings
            hwproduct = height * width
            tilesize = 1024.0 * 1024.0
            hwtileratio = hwproduct / tilesize
            # Round up number of tiles if map size (hwproduct) isn't evenly divisible by tilesize
            # Using floor division and negative numerator trick
            expected_tile_n_unzoomed = -(-hwproduct // tilesize)
            # Zoom value hints
            max_zoom_100 = sqrt(100 / hwtileratio)
            max_zoom_500 = sqrt(500 / hwtileratio)
            scale_zoom_100 = round(scale / max_zoom_100)
            scale_zoom_500 = round(scale / max_zoom_500)

            if SourceCRS != "EPSG:4326":
                projection_warning(iface)

            # create the dialog
            dlg = GarminCustomMapDialog()

            # Update the dialog
            dlg.textBrowser.setHtml(
                DIALOG_TEXT.format(
                    height=height,
                    width=width,
                    scale=round(scale),
                    expected_tile_n_unzoomed=expected_tile_n_unzoomed,
                    cap100=expected_tile_n_unzoomed / 100,
                    max_zoom_100=max_zoom_100,
                    scale_zoom_100=scale_zoom_100,
                    cap500=expected_tile_n_unzoomed / 500,
                    max_zoom_500=max_zoom_500,
                    scale_zoom_500=scale_zoom_500,
                )
            )

            # TODO: need to figure out a way to display one decimal place, but round down values
            # TODO: consider truncated division trunc()
            # TODO: try using the 'f' format string: f'{floatval:.1f}'
            dlg.zoom_100.setText(
                "Max. zoom for devices with  &lt;= 100 tiles: {!r:>5.5} (1:{})".format(
                    max_zoom_100, scale_zoom_100
                )
            )
            dlg.zoom_500.setText(
                "Max. zoom for devices with  &lt;= 500 tiles: {!r:>5.5} (1:{})".format(
                    max_zoom_500, scale_zoom_500
                )
            )

            # Show the dialog
            # TODO: Should be doing this in a separate signal call
            # connected to the OK button, this way the run method blocks the UI
            dlg.show()
            result = dlg.exec_()
            # See if OK was pressed
            if result == 1:
                produce_tiles(
                    optimize=dlg.flag_optimize.isChecked(),
                    tile_height=int(dlg.tile_height.value()),
                    tile_width=int(dlg.tile_width.value()),
                    quality=int(dlg.jpg_quality.value()),
                    dbg_flag=dlg.flag_dbgMsg.isChecked(),
                    draworder=dlg.draworder.value(),
                    zoom=float(dlg.zoom.value()),
                    kmz_file=kmz_file,
                    mapSettings=mapSettings,
                    mapRect=mapRect,
                    srs=srs,
                )
