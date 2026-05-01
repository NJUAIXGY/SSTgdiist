dnl -*- Autoconf -*-

AC_DEFUN([SST_SnnDL_CONFIG], [
  sst_check_SnnDL="yes"
  
  dnl Check for optional HDF5 support
  AC_ARG_WITH([hdf5],
    [AS_HELP_STRING([--with-hdf5], [Enable HDF5 support for SHD dataset format])],
    [with_hdf5=$withval],
    [with_hdf5=no])
  
  dnl Initialize HDF5 variables
  HDF5_CPPFLAGS=""
  HDF5_LDFLAGS=""
  HDF5_LIBS=""
  
  dnl Check for HDF5 if requested
  AS_IF([test "x$with_hdf5" != "xno"], [
    AC_CHECK_HEADERS([hdf5.h], [
      AC_CHECK_LIB([hdf5], [H5Fopen], [
        HDF5_LIBS="-lhdf5"
        AC_DEFINE([HAVE_HDF5], [1], [Define if HDF5 is available])
        AC_MSG_NOTICE([HDF5 support enabled])
      ], [
        AS_IF([test "x$with_hdf5" != "xcheck"], [
          AC_MSG_ERROR([HDF5 library not found])
        ])
      ])
    ], [
      AS_IF([test "x$with_hdf5" != "xcheck"], [
        AC_MSG_ERROR([HDF5 headers not found])
      ])
    ])
  ])
  
  dnl Substitute HDF5 variables
  AC_SUBST([HDF5_CPPFLAGS])
  AC_SUBST([HDF5_LDFLAGS])
  AC_SUBST([HDF5_LIBS])
  
  dnl Set conditional for HDF5 support in Makefiles
  AM_CONDITIONAL([HAVE_HDF5], [test "x$HDF5_LIBS" != "x"])
  
  dnl Execute success/failure actions
  AS_IF([test "$sst_check_SnnDL" = "yes"], [$1], [$2])
])
