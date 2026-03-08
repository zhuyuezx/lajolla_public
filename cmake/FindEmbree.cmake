# FindEmbree.cmake - Find Embree ray tracing library

set(EMBREE_ROOT ${CMAKE_SOURCE_DIR}/embree)

# Determine platform-specific library path
if(APPLE)
    # Check if we're on ARM64 (Apple Silicon)
    execute_process(
        COMMAND uname -m
        OUTPUT_VARIABLE ARCH
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    
    if(ARCH STREQUAL "arm64")
        set(EMBREE_LIB_DIR ${EMBREE_ROOT}/lib-macos/arm64)
    else()
        set(EMBREE_LIB_DIR ${EMBREE_ROOT}/lib-macos)
    endif()
elseif(UNIX)
    set(EMBREE_LIB_DIR ${EMBREE_ROOT}/lib-linux)
elseif(WIN32)
    set(EMBREE_LIB_DIR ${EMBREE_ROOT}/lib-win32)
endif()

# Find include directory
find_path(EMBREE_INCLUDE_PATH
    NAMES embree4/rtcore.h
    PATHS ${EMBREE_ROOT}/include
    NO_DEFAULT_PATH
)

# Find Embree library
find_library(EMBREE_LIBRARY
    NAMES embree4 libembree4
    PATHS ${EMBREE_LIB_DIR}
    NO_DEFAULT_PATH
)

# Find TBB library (required by Embree)
find_library(TBB_LIBRARY
    NAMES tbb libtbb
    PATHS ${EMBREE_LIB_DIR}
    NO_DEFAULT_PATH
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(Embree
    REQUIRED_VARS EMBREE_LIBRARY EMBREE_INCLUDE_PATH TBB_LIBRARY
)

if(EMBREE_FOUND)
    set(EMBREE_LIBRARIES ${EMBREE_LIBRARY} ${TBB_LIBRARY})
    set(EMBREE_INCLUDE_PATHS ${EMBREE_INCLUDE_PATH})
    
    if(NOT TARGET Embree::Embree)
        add_library(Embree::Embree UNKNOWN IMPORTED)
        set_target_properties(Embree::Embree PROPERTIES
            IMPORTED_LOCATION ${EMBREE_LIBRARY}
            INTERFACE_INCLUDE_DIRECTORIES ${EMBREE_INCLUDE_PATH}
            INTERFACE_LINK_LIBRARIES ${TBB_LIBRARY}
        )
    endif()
    
    message(STATUS "Found Embree: ${EMBREE_LIBRARY}")
    message(STATUS "Embree include path: ${EMBREE_INCLUDE_PATH}")
    message(STATUS "Using library directory: ${EMBREE_LIB_DIR}")
endif()

mark_as_advanced(EMBREE_INCLUDE_PATH EMBREE_LIBRARY TBB_LIBRARY)
