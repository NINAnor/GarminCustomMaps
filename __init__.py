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
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load GarminCustomMap class from file GarminCustomMap.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .GarminCustomMap import GarminCustomMap

    return GarminCustomMap(iface)
