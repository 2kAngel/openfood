from pythonforandroid.recipes.freetype import Freetype as OriginalFreetype

class Freetype(OriginalFreetype):
    version = "2.14.1"
    url = "https://downloads.sourceforge.net/project/freetype/freetype2/{version}/freetype-{version}.tar.gz"
    versioned_url = "https://downloads.sourceforge.net/project/freetype/freetype2/{version}/freetype-{version}.tar.gz"
    # Try alternative mirrors if sourceforge fails - p4a will retry with this url
    # Fallback URLs tried by p4a's download logic: url, then versioned_url
    # We override both to point to SourceForge which is more reliable than Savannah

recipe = Freetype()
