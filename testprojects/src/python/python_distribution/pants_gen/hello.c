#include <Python.h>

#ifndef HELLO_STR
#error "HELLO_STR macro was not defined!"
#endif

static PyObject * hello(PyObject *self, PyObject *args) {
  return Py_BuildValue("s", HELLO_STR);
}

static PyMethodDef Methods[] = {
  {"hello", hello, METH_VARARGS, "Yet Another Hello World Implementation."},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC inithello(void) {
  (void) Py_InitModule("hello", Methods);
}
